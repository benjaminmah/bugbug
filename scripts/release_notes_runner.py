import argparse
import logging

from bugbug import db
from bugbug.bugzilla import BUGS_DB
from bugbug.tools.release_notes import ReleaseNotesGenerator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Generate Firefox release notes.")
    parser.add_argument(
        "--repo", default="hg_dir", help="Path to the Mercurial repository"
    )
    parser.add_argument("--version", required=True, help="Target version identifier")
    parser.add_argument(
        "--chunk-size", type=int, default=10000, help="Chunk size for token processing"
    )

    args = parser.parse_args()

    generator = ReleaseNotesGenerator(
        repo_directory=args.repo,
        version=args.version,
        chunk_size=args.chunk_size,
    )
    generator.generate_worthy_commits(version=args.version)


if __name__ == "__main__":
    db.download(BUGS_DB)
    main()
