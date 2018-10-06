"""GoogleFonts Dispatcher"""
import subprocess
import argparse
import os
import logging

from repo import GFRepo
from upstream import UpstreamRepo
from settings import SETTINGS
from utils import get_repo_family_name


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def pr_family_to_googlefonts(repo_url, license, fonts, upstream_commit,
                             html_snippet=None):
    """Send a family pr to a google/fonts repo"""
    repo = GFRepo()
    family_name = get_repo_family_name(fonts)

    if repo.has_family(family_name):
        logger.info('Family already exists. Replacing files')
        family = repo.get_family(family_name)
        family.replace_fonts(fonts)
        family.replace_file(license)
        family.update_metadata()
    else:
        logger.info('Family does not exist. Adding files')
        family = repo.new_family(license, family_name)
        family.add_fonts(fonts)
        family.add_file(license)
        if html_snippet:
            family.add_file(html_snippet)
        family.generate_metadata(input_designer=True, input_category=True)

    commit_msg = repo.commit(family_name, repo_url, upstream_commit)
    repo.pull_request(commit_msg)


def pr_from_github_to_googlefonts(upstream_url, upstream_fonts_dir, license_dir=None):
    logger.info('Downloading license and fonts from {}'.format(upstream_url))

    upstream_repo = UpstreamRepo(upstream_url, upstream_fonts_dir,
                                 license_dir=license_dir)

    for family in upstream_repo.families:
        logger.info('PRing {} to google/fonts repo'.format(family))
        pr_family_to_googlefonts(
            upstream_url,
            upstream_repo.license,
            upstream_repo.families[family],
            upstream_repo.commit,
            html_snippet=upstream_repo.html_snippet
        )
        git_cleanup()


def main():
    """User specifies an upstream repository url and the dir containing the shipped fonts.

    Once finished, the temporary directories containing the reports, images
    and upstream fonts will be removed"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_url")
    parser.add_argument("repo_fonts_dir")
    parser.add_argument("--license_dir")
    args = parser.parse_args()
    pr_from_github_to_googlefonts(
        args.repo_url,
        args.repo_fonts_dir, 
        args.license_dir
    )


def git_cleanup():
    cwd = os.getcwd()
    os.chdir(SETTINGS['local_gf_repo_path'])
    subprocess.call(['git', 'stash'])
    subprocess.call(['git', 'checkout', 'master'])
    subprocess.call(['git', 'reset', '--hard'])
    subprocess.call(['git', "clean", '-f'])
    logger.info("Repo {} reset back to master.".format(SETTINGS['local_gf_repo_path']))
    os.chdir(cwd)


if __name__ == '__main__':
    main()
