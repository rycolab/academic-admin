import calendar
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

import bibtexparser
from bibtexparser.bibdatabase import BibDatabase
from bibtexparser.bparser import BibTexParser
from bibtexparser.bwriter import BibTexWriter
from bibtexparser.customization import convert_to_unicode

from academic import utils
from academic.editFM import EditableFM

# Map BibTeX to Academic publication types.
PUB_TYPES = {
    "article": 2,
    "book": 5,
    "inbook": 6,
    "incollection": 6,
    "inproceedings": 1,
    "manual": 4,
    "mastersthesis": 7,
    "misc": 0,
    "phdthesis": 7,
    "proceedings": 0,
    "techreport": 4,
    "unpublished": 3,
    "patent": 8,
}

def import_bibtex(bibtex, pub_dir="publication", featured=False, overwrite=False, normalize=False, dry_run=False):
    """Import publications from BibTeX file"""
    from academic.cli import AcademicError, log
    # Check BibTeX file exists.
    if not Path(bibtex).is_file():
        err = "Please check the path to your BibTeX file and re-run"
        log.error(err)
        raise AcademicError(err)

    # Load BibTeX file for parsing.
    with open(bibtex, "r", encoding="utf-8") as bibtex_file:
        parser = BibTexParser(common_strings=True)
        parser.customization = convert_to_unicode
        parser.ignore_nonstandard_types = False
        bib_database = bibtexparser.load(bibtex_file, parser=parser)
        for entry in bib_database.entries:
            parse_bibtex_entry(entry, pub_dir=pub_dir, featured=featured, overwrite=overwrite, normalize=normalize, dry_run=dry_run)


def parse_bibtex_entry(entry, pub_dir="publication", featured=False, overwrite=False, normalize=False, dry_run=False):
    from academic.cli import log, LINKS_HEADER, ANTHOLOGY_LINK, ARXIV_LINK
    """Parse a bibtex entry and generate corresponding publication bundle"""
    log.info(f"Parsing entry {entry['ID']}")

    bundle_path = f"content/{pub_dir}/{slugify(entry['ID'])}"
    markdown_path = os.path.join(bundle_path, "index.md")
    cite_path = os.path.join(bundle_path, "cite.bib")
    date = datetime.utcnow()
    timestamp = date.isoformat("T") + "Z"  # RFC 3339 timestamp.

    # Do not overwrite publication bundle if it already exists.
    if not overwrite and os.path.isdir(bundle_path):
        log.warning(f"Skipping creation of {bundle_path} as it already exists. " f"To overwrite, add the `--overwrite` argument.")
        return

    # Create bundle dir.
    log.info(f"Creating folder {bundle_path}")
    if not dry_run:
        Path(bundle_path).mkdir(parents=True, exist_ok=True)

    # Prepare YAML front matter for Markdown file.
    frontmatter = ["---"]
    frontmatter.append(f'title: "{clean_bibtex_str(entry["title"])}"')
    year = ""
    month = "01"
    day = "01"
    if "date" in entry:
        dateparts = entry["date"].split("-")
        if len(dateparts) == 3:
            year, month, day = dateparts[0], dateparts[1], dateparts[2]
        elif len(dateparts) == 2:
            year, month = dateparts[0], dateparts[1]
        elif len(dateparts) == 1:
            year = dateparts[0]
    if "month" in entry and month == "01":
        month = month2number(entry["month"])
    if "year" in entry and year == "":
        year = entry["year"]
    if len(year) == 0:
        log.error(f'Invalid date for entry `{entry["ID"]}`.')
    frontmatter.append(f"date: {year}-{month}-{day}")

    frontmatter.append(f"publishDate: {timestamp}")

    authors = None
    if "author" in entry:
        authors = entry["author"]
    elif "editor" in entry:
        authors = entry["editor"]
    if authors:
        authors = clean_bibtex_authors([i.strip() for i in authors.replace("\n", " ").split(" and ")])
        frontmatter.append(f"authors: [{', '.join(authors)}]")

    frontmatter.append(f'publication_types: ["{PUB_TYPES.get(entry["ENTRYTYPE"], 0)}"]')

    if "abstract" in entry:
        frontmatter.append(f'abstract: "{clean_bibtex_str(entry["abstract"])}"')
    else:
        frontmatter.append('abstract: ""')

    frontmatter.append(f"featured: {str(featured).lower()}")

    # Publication name.
    if "booktitle" in entry:
        frontmatter.append(f'publication: "*{clean_bibtex_str(entry["booktitle"])}*"')
    elif "journal" in entry:
        frontmatter.append(f'publication: "*{clean_bibtex_str(entry["journal"])}*"')
    elif "publisher" in entry:
        frontmatter.append(f'publication: "*{clean_bibtex_str(entry["publisher"])}*"')
    else:
        frontmatter.append('publication: ""')
    if "venue" in entry: 
        frontmatter.append(f'publication_short: "{clean_bibtex_str(entry["venue"])}"')
        del entry["venue"]

    if "keywords" in entry:
        frontmatter.append(f'tags: [{clean_bibtex_tags(entry["keywords"], normalize)}]')
    if "arxiv" or "anthology" in entry:
        frontmatter.append(LINKS_HEADER)
    if "anthology" in entry:
        frontmatter.append(ANTHOLOGY_LINK + clean_bibtex_str(entry["anthology"]))
        del entry["anthology"]
    if "arxiv" in entry:
        frontmatter.append(ARXIV_LINK + clean_bibtex_str(entry["arxiv"]))
    if "doi" in entry:
        frontmatter.append(f'doi: "{entry["doi"]}"')

    if "recent" in entry:
        frontmatter.append(f'recent: {entry["recent"]}')
        del entry['recent']

    frontmatter.append(f'url_pdf: papers/'+entry['ID']+'.pdf') 
    if 'code' in entry:
        frontmatter.append(f'url_code: '+entry['code'])  
        del entry['code']

    frontmatter.append("---\n\n")

    # Save citation file.
    log.info(f"Saving citation to {cite_path}")
    db = BibDatabase()
    db.entries = [entry]
    writer = BibTexWriter()
    writer.display_order = ["title", "author", "booktitle", "month", "year", "address", "publisher",\
                         "pages","volume", "url", "arxiv", "abstract"]
    if not dry_run:
        with open(cite_path, "w", encoding="utf-8") as f:
            f.write(writer.write(db))


    # Save Markdown file.
    try:
        log.info(f"Saving Markdown to '{markdown_path}'")
        if not dry_run:
            with open(markdown_path, "w", encoding="utf-8") as f:
                f.write("\n".join(frontmatter))
    except IOError:
        log.error("Could not save file.")


def slugify(s, lower=True):
    bad_symbols = (".", "_", ":")  # Symbols to replace with hyphen delimiter.
    delimiter = "-"
    good_symbols = (delimiter,)  # Symbols to keep.
    for r in bad_symbols:
        s = s.replace(r, delimiter)

    s = re.sub(r"(\D+)(\d+)", r"\1\-\2", s)  # Delimit non-number, number.
    s = re.sub(r"(\d+)(\D+)", r"\1\-\2", s)  # Delimit number, non-number.
    s = re.sub(r"((?<=[a-z])[A-Z]|(?<!\A)[A-Z](?=[a-z]))", r"\-\1", s)  # Delimit camelcase.
    s = "".join(c for c in s if c.isalnum() or c in good_symbols).strip()  # Strip non-alphanumeric and non-hyphen.
    s = re.sub("-{2,}", "-", s)  # Remove consecutive hyphens.

    if lower:
        s = s.lower()
    return s


def clean_bibtex_authors(author_str):
    """Convert author names to `firstname(s) lastname` format."""
    authors = []
    for s in author_str:
        s = s.strip()
        if len(s) < 1:
            continue
        if "," in s:
            split_names = s.split(",", 1)
            last_name = split_names[0].strip()
            first_names = [i.strip() for i in split_names[1].split()]
        else:
            split_names = s.split()
            last_name = split_names.pop()
            first_names = [i.replace(".", ". ").strip() for i in split_names]
        if last_name in ["jnr", "jr", "junior"]:
            last_name = first_names.pop()
        for item in first_names:
            if item in ["ben", "van", "der", "de", "la", "le"]:
                last_name = first_names.pop() + " " + last_name
        authors.append(f'"{" ".join(first_names)} {last_name}"')
    return authors


def clean_bibtex_str(s):
    """Clean BibTeX string and escape TOML special characters"""
    s = s.replace("\\", "")
    s = s.replace('"', '\\"')
    s = s.replace("{", "").replace("}", "")
    s = s.replace("\t", " ").replace("\n", " ").replace("\r", "")
    return s


def clean_bibtex_tags(s, normalize=False):
    """Clean BibTeX keywords and convert to TOML tags"""
    tags = clean_bibtex_str(s).split(",")
    tags = [f'"{tag.strip()}"' for tag in tags]
    if normalize:
        tags = [tag.capitalize() for tag in tags]
    tags_str = ", ".join(tags)
    return tags_str


def month2number(month):
    from academic.cli import log
    """Convert BibTeX or BibLateX month to numeric"""
    if len(month) <= 2:  # Assume a 1 or 2 digit numeric month has been given.
        return month.zfill(2)
    else:  # Assume a textual month has been given.
        month_abbr = month.strip()[:3].title()
        try:
            return str(list(calendar.month_abbr).index(month_abbr)).zfill(2)
        except ValueError:
            raise log.error("Please update the entry with a valid month.")
