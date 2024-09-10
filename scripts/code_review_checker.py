import csv
from collections import defaultdict

from libmozdata.phabricator import PhabricatorAPI

from bugbug import db, phabricator
from bugbug.utils import get_secret

# define the required key phabricator (config.PHABRICATOR_API_KEY)
db.download(phabricator.REVISIONS_DB)

# download all available revisions
rev = PhabricatorAPI(get_secret("PHABRICATOR_TOKEN"))


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


def check_for_other_comments_on_same_line(transactions, comment_ids):
    comment_lines = {}
    same_line_comments = {}

    for transaction in transactions:
        if len(transaction["fields"]) > 0 and len(transaction["comments"]) > 0:
            for comment in transaction["comments"]:
                if comment["id"] in comment_ids:
                    line_number = transaction["fields"]["line"]
                    comment_lines[comment["id"]] = line_number

    for comment_id, line_number in comment_lines.items():
        other_comments = False
        for transaction in transactions:
            if len(transaction["fields"]) > 0 and len(transaction["comments"]) > 0:
                for comment in transaction["comments"]:
                    if (
                        comment["id"] != comment_id
                        and transaction["fields"]["line"] == line_number
                    ):
                        other_comments = True
                        break
        same_line_comments[comment_id] = other_comments

    return same_line_comments


def check_for_other_comments_in_hunk(transactions, comment_ids, hunk_range=10):
    comment_lines = {}
    hunk_comments = {}

    for transaction in transactions:
        if len(transaction["fields"]) > 0 and len(transaction["comments"]) > 0:
            for comment in transaction["comments"]:
                if comment["id"] in comment_ids:
                    line_number = transaction["fields"]["line"]
                    comment_lines[comment["id"]] = line_number

    for comment_id, line_number in comment_lines.items():
        other_comments_in_hunk = False
        for transaction in transactions:
            if len(transaction["fields"]) > 0 and len(transaction["comments"]) > 0:
                for comment in transaction["comments"]:
                    if comment["id"] != comment_id:
                        comment_line = transaction["fields"]["line"]
                        if (
                            line_number - hunk_range
                            <= comment_line
                            <= line_number + hunk_range
                        ):
                            other_comments_in_hunk = True
                            break
        hunk_comments[comment_id] = other_comments_in_hunk

    return hunk_comments


def generate_report(
    target_file, comments_report, same_line_report, hunk_report, target_revision
):
    with open(target_file, mode="a", newline="") as file:
        writer = csv.writer(file)

        for comment_report, status in comments_report.items():
            same_line_exists = same_line_report.get(comment_report, False)
            hunk_exists = hunk_report.get(comment_report, False)
            writer.writerow(
                [target_revision, comment_report, status, same_line_exists, hunk_exists]
            )


def run_analysis(target_file):
    revisions = get_target_revisions()

    for revision in phabricator.get_revisions():
        if revision["id"] in revisions.keys():
            try:
                revision_comments = check_for_replies_on_target_comments(
                    revision["transactions"], revisions.get(revision["id"])
                )

                same_line_comments = check_for_other_comments_on_same_line(
                    revision["transactions"], revisions.get(revision["id"])
                )

                hunk_comments = check_for_other_comments_in_hunk(
                    revision["transactions"],
                    revisions.get(revision["id"]),
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


run_analysis("comment-status.csv")
