#!/usr/bin/env python3

import os
from icalendar import Calendar, Todo
import dateutil.parser
from datetime import datetime
import argparse
import re
from dotenv import load_dotenv
import hashlib

import logging
# logging.basicConfig()
# logging.getLogger().setLevel(logging.DEBUG)

# TODO add support for [x]it! (harder because subtasks require context and icalendar does not support sub-tasks)
# TODO add some fuzzy logic to handle minor typos
# TODO add proper unit tests
# TODO add http a server

TAGS_PATTERN = r"([^\s:]+):(?!\/\/)([^\s]+)"
PROJECT_PATTERN = r" \+(\w+)"
CONTEXT_PATTERN = r" @(\w+)"
DATE_PATTERN = r"([0-9]{4}-[0-9]{2}-[0-9]{2}(T[0-9]{2}:[0-9]{2}(:[0-9]{2})?)?)"
GH_PATTERN = r"^- \[(?P<status> |x|\@|\~)\] (?:(\(?P<priority>[A-Z]\)) )?(?:(?P<completed>[0-9]{4}-[0-9]{2}-[0-9]{2}(T[0-9]{2}:[0-9]{2}(:[0-9]{2})?)? )?(?P<created>[0-9]{4}-[0-9]{2}-[0-9]{2}(T[0-9]{2}:[0-9]{2}(:[0-9]{2})?)?))?"
KEYWORD_PATTERN = (
    r"^- (?P<status>TODO|DONE|EXPIRED|CANCELL?ED|NEEDS-ACTION|COMPLETED|IN-PROCESS)"
)
TDTXT_PATTERN = r"^- (?:(?P<status>x) )?(?:(\(?P<priority>[A-Z]\)) )?(?:(?P<completed>[0-9]{4}-[0-9]{2}-[0-9]{2}(T[0-9]{2}:[0-9]{2}(:[0-9]{2})?)? )?(?P<created>[0-9]{4}-[0-9]{2}-[0-9]{2}(T[0-9]{2}:[0-9]{2}(:[0-9]{2})?)?))"


def parse_date(value):
    rematch = re.match(DATE_PATTERN, value)
    return dateutil.parser.isoparse(rematch.group(1))


def parse_status(value):
    # Valid VTODO statuses are listed in the RFC https://www.rfc-editor.org/rfc/rfc5545#section-3.8.1.11
    match value.upper():
        # We mark cancelled as completed because Thunderbird shows cancelled tasks https://bugzilla.mozilla.org/show_bug.cgi?id=382363
        case "CANCELLED" | "EXPIRED" | "DONE" | "X" | "~" :
            return "COMPLETED"
        case "TODO" | " ":
            return ""
        case "@":
            return "IN-PROGRESS"
        case _:
            raise Exception("Status not recognized: {}".format(value))


TAG_PARSE = {
    "created": parse_date,
    "completed": parse_date,
    "status": parse_status,
    "due": parse_date,
    "start": parse_date,
    "dtstamp": parse_date,
    "location": lambda value: value,
    "categories": lambda value: value.split(","),
}


def make_todo(line):
    tags = dict()

    rematch = re.match(GH_PATTERN, line, re.IGNORECASE)
    if rematch:
        # matched a Github-style task.
        tags.update(rematch.groupdict())
    else:
        rematch = re.match(KEYWORD_PATTERN, line, re.IGNORECASE)
        if rematch:
            # matched a keyword-style task.
            tags.update(rematch.groupdict())
        else:
            rematch = re.match(TDTXT_PATTERN, line, re.IGNORECASE)
            if rematch:
                # matched a todo.txt style task.
                tags.update(rematch.groupdict())
            else:
                # doesn't look like a task.
                return

    summary = line[len(rematch.group(0)) :].strip()
    if len(summary) == 0:
        # skip tasks without a summary.
        return

    todo = Todo()

    tags.update(dict(re.findall(TAGS_PATTERN, summary)))

    # map various parsed tags into vtodo tags.
    for key, value in tags.items():
        if not key in TAG_PARSE:
            logging.info("An unknown field was detected: {}".format(key))
        if value and key in TAG_PARSE:
            parse = TAG_PARSE[key]
            parsed_value = parse(value)
            if parsed_value:
                todo.add(key, parsed_value)
                # cleanup the summary (note the space)
                summary = summary.replace(" {}:{}".format(key, value), " ")

    todo.add("categories", re.findall(PROJECT_PATTERN, summary))
    summary = re.sub(PROJECT_PATTERN, "", summary)

    todo.add("resources", re.findall(CONTEXT_PATTERN, summary))
    summary = re.sub(CONTEXT_PATTERN, "", summary)

    # todo.add("categories", [rematch.group(0) for rematch in re.findall(PROJECT_PATTERN, summary)])
    # generate a vtodo uid based on the summary checksum (can be useful with caldav sync)
    todo.add("uid", hashlib.sha256(line.encode("utf-8")).hexdigest())
    if not "dtstamp" in todo:
        todo.add("dtstamp", datetime.now())

    # FIXME if we require a strip here it could mean our patterns are not perfect
    todo.add("summary", summary.strip())
    return todo


def make_calendar(args):
    cal = Calendar()
    if args.infile:
        for line in args.infile:
            todo = make_todo(line)
            if todo:
                cal.add_component(todo)

    try:
        # line endings are part of the iCal standard, so if we're writing to a file
        # we need to write the bytes.
        args.outfile.write(cal.to_ical())
    except TypeError:
        # Writing to stdout is a bit different, as it requires an str on Linux. On
        # Windows stdout accepts a byte.
        args.outfile.write(cal.to_ical().decode("utf-8"))


load_dotenv()

parser = argparse.ArgumentParser(
    description="Converts TODOs in a text file into an iCal file."
)
parser.add_argument(
    "infile",
    nargs="?",
    type=argparse.FileType("r", encoding="utf-8"),
    default=os.getenv("infile"),
)
parser.add_argument(
    "--outfile", type=argparse.FileType("wb"), default=os.getenv("outfile") or "-"
)

make_calendar(parser.parse_args())
