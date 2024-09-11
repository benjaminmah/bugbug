import csv
import os
from collections import defaultdict

from libmozdata.phabricator import PhabricatorAPI

from bugbug import db, phabricator
from bugbug.tools.code_review import PhabricatorReviewData
from bugbug.utils import get_secret

# define the required key phabricator (config.PHABRICATOR_API_KEY)
db.download(phabricator.REVISIONS_DB)

# download all available revisions
rev = PhabricatorAPI(get_secret("PHABRICATOR_TOKEN"))
review_data = PhabricatorReviewData()


def get_target_revisions():
    data_dict = defaultdict(list)

    with open("input.csv", mode="r") as file:
        reader = csv.DictReader(file)
        for row in reader:
            revision_id = int(row["revision_id"])
            inline_comment_id = int(row["inline_comment_id"])
            data_dict[revision_id].append(inline_comment_id)

    return dict(data_dict)


def collect_phid_from_comment_ids(transactions, comment_ids):
    comment_phids = {}

    for transaction in transactions:
        if len(transaction["fields"]) > 0 and len(transaction["comments"]) > 0:
            for comment in transaction["comments"]:
                if comment["id"] in comment_ids:
                    comment_phids[comment["phid"]] = comment["id"]

    return comment_phids


def check_for_replies_on_target_comments(transactions, comment_ids):
    comment_phids = collect_phid_from_comment_ids(transactions, comment_ids)
    comment_status = {}

    for transaction in transactions:
        if (
            len(transaction["fields"]) > 0 and len(transaction["comments"]) > 0
        ) and transaction["fields"]["replyToCommentPHID"] in comment_phids.keys():
            comment_status[
                comment_phids.get(transaction["fields"]["replyToCommentPHID"])
            ] = True

    for comment_id in comment_ids:
        if comment_id not in comment_status:
            comment_status[comment_id] = False

    return comment_status


def check_for_comments_in_hunk(transactions, comment_ids, hunk_range=0):
    comment_information = {}
    same_hunk_comments = defaultdict(list)

    # Filter inline comments and populate comment_information
    for transaction in transactions:
        if (
            transaction["type"] != "inline"
            or not transaction["fields"]
            or not transaction["comments"]
        ):
            continue

        for comment in transaction["comments"]:
            if comment["id"] in comment_ids:
                comment_information[comment["id"]] = (
                    transaction["fields"]["line"],
                    transaction["fields"]["path"],
                    transaction["dateCreated"],
                )

    # Check for comments in the same hunk
    for transaction in transactions:
        if (
            transaction["type"] != "inline"
            or not transaction["fields"]
            or not transaction["comments"]
        ):
            continue

        current_comment_line = transaction["fields"]["line"]
        current_comment_file_path = transaction["fields"]["path"]

        for comment in transaction["comments"]:
            for comment_id, (
                line_number,
                file_path,
                date_created,
            ) in comment_information.items():
                if (
                    comment["dateCreated"] > date_created
                    and comment["id"] != comment_id
                    and file_path == current_comment_file_path
                ):
                    if (
                        line_number - hunk_range
                        <= current_comment_line
                        <= line_number + hunk_range
                    ):
                        same_hunk_comments[comment_id].append(comment)
    return same_hunk_comments


def generate_report(
    target_file,
    comments_report,
    same_line_comment_report,
    same_hunk_comment_report,
    target_revision,
):
    file_exists = os.path.isfile(target_file)
    file_is_empty = os.stat(target_file).st_size == 0 if file_exists else True

    with open(target_file, mode="a", newline="") as file:
        writer = csv.writer(file)

        if file_is_empty:
            writer.writerow(
                [
                    "Revision",
                    "Comment",
                    "Status",
                    "Same Line Comment Exists",
                    "Same Line Comments",
                    "Same Hunk Comment Exists",
                    "Same Hunk Comments",
                ]
            )

        for comment_report, status in comments_report.items():
            same_line_exists = bool(same_line_comment_report.get(comment_report, {}))
            hunk_exists = bool(same_hunk_comment_report.get(comment_report, {}))

            writer.writerow(
                [
                    target_revision,
                    comment_report,
                    status,
                    same_line_exists,
                    same_line_comment_report.get(comment_report, {}),
                    hunk_exists,
                    same_hunk_comment_report.get(comment_report, {}),
                ]
            )


def run_analysis(target_file):
    revisions = get_target_revisions()

    for revision in phabricator.get_revisions():
        if revision["id"] in revisions.keys():
            print(revision["id"])
            try:
                revision_comments = check_for_replies_on_target_comments(
                    revision["transactions"], revisions.get(revision["id"])
                )

                same_line_comments = check_for_comments_in_hunk(
                    transactions=revision["transactions"],
                    comment_ids=revisions.get(revision["id"]),
                    hunk_range=0,
                )

                hunk_comments = check_for_comments_in_hunk(
                    transactions=revision["transactions"],
                    comment_ids=revisions.get(revision["id"]),
                    hunk_range=10,
                )

                generate_report(
                    target_file,
                    revision_comments,
                    same_line_comments,
                    hunk_comments,
                    revision["id"],
                )

            except Exception as e:
                print(e)


if __name__ == "__main__":
    run_analysis("comment-status.csv")
