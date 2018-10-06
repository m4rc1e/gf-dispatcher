# -*- coding: utf-8 -*-
import os
from os.path import basename
from glob import glob
import shutil
import subprocess
import shutil
from fontTools.ttLib import TTFont
import requests
import time
import tempfile
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive

from utils import md5_checksum
from settings import SETTINGS 

from exceptions import (
    MultipleFamilies,
    IncorrectFontFormat,
    InsufficientFonts,
    FontsAreIdentical
)

REPO_DIRS = {
    'OFL.txt': 'ofl',
    'UFL.txt': 'ufl',
    'LICENSE.txt': 'apache'
}


class Family(object):
    """Wrapper to manipulate individual font folders which reside in the
    Google Fonts repository"""
    def __init__(self, path):
        self.path = path
        self.name = self._get_name(path)
        self.files = os.listdir(path)
        self.fonts = glob(os.path.join(path, '*.ttf'))
        self.is_updated = False

    def _get_name(self, path):
        return os.path.basename(path)

    def replace_fonts(self, files):
        """Replace the existing set of fonts with a new set.

        Only replace the fonts if they are .ttfs, all fonts
        get replaced at once and they are not the same as the
        existing fonts."""
        file_types = [os.path.splitext(f)[1] for f in files]
        if '.ttf' not in set(file_types):
            raise IncorrectFontFormat

        old_filenames = map(os.path.basename, self.fonts)
        new_filenames = map(os.path.basename, files)
        if len(set(old_filenames) - set(new_filenames)) > 0:
            raise InsufficientFonts(self.fonts, files)

        fonts_hash = {basename(f): md5_checksum(f) for f in self.fonts}
        new_fonts_hash = {basename(f): md5_checksum(f) for f in files}
        shared_fonts = set(fonts_hash) & set(new_fonts_hash)
        for font in shared_fonts:
            if fonts_hash[font] == new_fonts_hash[font]:
                raise FontsAreIdentical

        map(os.remove, self.fonts)
        for f in files:
            shutil.copy(f, self.path)
        self.fonts = glob(os.path.join(self.path, '*.ttf'))
        self.is_updated = True

    def add_fonts(self, files):
        """Add .ttf fonts to family dir"""
        if self.fonts:
            raise Exception('Fonts already exist in dir. You can only '
                            'add new fonts to an empty dir. To '
                            'add additional styles, use replace fonts.')
        file_types = [os.path.splitext(f)[1] for f in files]
        if '.ttf' not in set(file_types):
            raise IncorrectFontFormat

        for f in files:
            shutil.copy(f, self.path)
        self.fonts = glob(os.path.join(self.path, '*.ttf'))

    def add_file(self, file_path):
        accepted_filenames = [
            'DESCRIPTION.en_us.html',
            'OFL.txt', 'UFL.txt', 'LICENCE.txt',
            'FONTLOG.txt']
        filename = basename(file_path)
        if filename not in accepted_filenames:
            raise Exception('File {} is not allowed. Ony the following files '
                            'are allowed: [{}]'.format(
                                filename, ', '.join(accepted_filenames)))
        shutil.copy(file_path, self.path)

    def replace_file(self, file):
        new_filename = basename(file)
        if new_filename not in self.files:
            raise Exception('{} does not exist'.format(new_filename))
        shutil.copy(file, self.path)

    def generate_metadata(self, input_designer=False, input_category=False):
        """
        input_designer: input prompt for designer name
        input_category: input prompt for family category
        """
        c_path = os.getcwd()
        if not SETTINGS['gf_add_font']:
            raise Exception('Provide path to gftools. Download from '
                            'https://github.com/googlefonts/tools')
        os.chdir(SETTINGS['gf_add_font'])
        add_font_tool = os.path.join(SETTINGS['gf_add_font'], 'bin', 'gftools-add-font.py')
        subprocess.call(['python', add_font_tool, self.path])

        metadata_path = os.path.join(self.path, 'METADATA.pb')
        if input_designer or input_category:
            metadata = open(metadata_path, 'r')
            metadata_text = metadata.read()
            metadata.close()

            if input_designer:
                designer = raw_input('designer: ')
                metadata_text = metadata_text.replace(
                    'designer: "UNKNOWN"',
                    'designer: "{}"'.format(designer)
                )
            if input_category:
                category_map = {
                    '1': 'SANS_SERIF',
                    '2': 'SERIF',
                    '3': 'DISPLAY',
                    '4': 'HANDWRITING',
                    '5': 'MONOSPACE'
                }
                category = raw_input('category (choices {}: '.format(
                    str(category_map).replace(': ', '='))
                )
                selected_category = category_map[category]
                metadata_text = metadata_text.replace(
                    'category: "SANS_SERIF"', 'category: "{}"'.format(
                        selected_category)
                )
            with open(metadata_path, 'w') as metadata:
                metadata.write(metadata_text)
        os.chdir(c_path)

    def update_metadata(self):
        c_path = os.getcwd()
        if not SETTINGS['gf_add_font']:
            raise Exception('Provide path to gftools. Download from '
                            'https://github.com/googlefonts/tools')
        os.chdir(SETTINGS['gf_add_font'])
        add_font_tool = os.path.join(SETTINGS['gf_add_font'], 'bin', 'gftools-add-font.py')
        subprocess.call(['python', add_font_tool, '--update', self.path])
        os.chdir(c_path)


class GFRepo(object):
    """Wrapper to manipulate a local and remote google/fonts repository

    The repository contains font families which are served on
    fonts.google.com. Families are organised by license type in the following
    tree structure.

    .
    ├── apache
    │   └── family1
    ├── ofl
    │   ├── family2
    │   │   ├── DESCRIPTION.en_us.html
    │   │   ├── METADATA.pb
    │   │   ├── OFL.txt
    │   │   └── family1-regular.ttf
    │   └── family3
    └── ufl
        └── family4


    When a font family is prd to the remote repo. The files will be
    tested in a sandboxed version of fonts.google.com and then rolled
    out to fonts.google.com.
    """
    def __init__(self):
        self.path = SETTINGS['local_gf_repo_path']
        self.path_ofl = os.path.join(self.path, 'ofl')
        self.path_ufl = os.path.join(self.path, 'ufl')
        self.path_apache = os.path.join(self.path, 'apache')
        self.families = self._get_families()

    def has_family(self, name):
        if name in self.families:
            return True
        return False

    def get_family(self, name):
        if self.has_family(name):
            return self.families[name]
        return None

    def new_family(self, license, name):
        """Create an empty Family. The license file is used to determine
        where the family should reside e.g If the family's license is ofl,
        the family will be in the ofl directory."""
        license_filename = basename(license)
        license_dir = REPO_DIRS[license_filename]
        path = os.path.join(self.path, license_dir, name)
        os.mkdir(path)
        self.families[name] = Family(path)
        return self.families[name]

    def update_family(self, family):
        family = self.families[family]
        family.update_metadata()

    def delete_family(self, name):
        family = self.get_family(name)
        shutil.rmtree(family.path)
        del self.families[name]

    def commit(self, family_name, repo_url, upstream_commit):
        """Make a git commit and push to remote repo"""
        family = self.families[family_name]

        os.chdir(self.path)
        # Delete local and remote branches if they already exist
        subprocess.call(['git', 'checkout', 'master'])
        subprocess.call(['git', 'branch', '-D', family_name])
        subprocess.call(['git', 'push', SETTINGS['git_remote'], ':{}'.format(family_name)])

        subprocess.call(['git', 'checkout', '-b', family_name])
        subprocess.call(['git', 'add', family.path])
        msg = self._commit_msg(family.name, family.fonts, repo_url, upstream_commit)
        subprocess.call(['git', 'commit', '-m', msg])
        subprocess.call(['git', 'push', SETTINGS['git_remote']])
        return msg

    def _commit_msg(self, name, fonts, repo_url, upstream_commit):
        """
        Generate a git commit message. For brevity, the FB reports are not
        included in commit messages. They appear in the pull request text"""
        with open(fonts[0], 'r') as font_path:
            version = TTFont(font_path)['head'].fontRevision
            version = '%.3f' % round(version, 3)
            msg = '{}: v{} added\n\nTaken from the upstream repo {} at commit {}'.format(
                name, version, repo_url, upstream_commit)
            return msg

    def pull_request(self, commit_msg):
        subprocess.call(['hub', 'pull-request', '-b', 'm4rc1e/fonts:master', '-m', commit_msg, '-f'])

    def git_reset(self):
        c_dir = os.getcwd()
        os.chdir(self.path)
        subprocess.call(['git', 'checkout', 'master'])
        subprocess.call(['git', 'reset', '--hard'])

    def _get_families(self):
        """Get all the families in the repo"""
        families = {}
        for directory in (self.path_ofl, self.path_ufl, self.path_apache):
            for family_dir in os.listdir(directory):
                if not '.' in family_dir:
                    family_path = os.path.join(self.path, directory, family_dir)
                    families[family_dir] = Family(family_path)
        return families
