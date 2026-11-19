"""Prepare a reviewed legacy-compatible policy from a pinned geosite archive.

Writes a candidate and an internal report only. Does not contact production or
change the separate mobile-operator whitelist catalog.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.russian_routing_import import import_geosite, merge_russian_policy
from app.services.routing_policy import build_policy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--current', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--include-country-zones', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9a-f]{40}', args.source_commit):
        parser.error('Expected a pinned source commit')
    paths = [args.archive, args.current, args.output, args.report]
    if len({path.resolve() for path in paths}) != len(paths):
        parser.error('Input and output paths must be distinct')
    if args.current.stat().st_size > 240000 or args.archive.stat().st_size > 2*1024*1024:
        parser.error('Input exceeds limits')
    current = json.loads(args.current.read_text(encoding='utf-8'))
    if current.get('schema_version') != 1 or current.get('profile'):
        parser.error('Expected the normal production routing policy')
    normalized = build_policy(current['direct_domains'], current['vpn_domains'])
    if normalized['revision'] != current.get('revision'):
        parser.error('Current policy revision does not match its content')
    data = args.archive.read_bytes()
    candidate, report = merge_russian_policy(current, import_geosite(data),
        include_country_zones=args.include_country_zones)
    report.update({'source': 'https://github.com/v2fly/domain-list-community',
        'source_commit': args.source_commit, 'source_license': 'MIT',
        'source_archive_sha256': hashlib.sha256(data).hexdigest(),
        'before_revision': normalized['revision'], 'candidate_revision': candidate['revision'],
        'direct_count': len(candidate['direct_domains']), 'vpn_count': len(candidate['vpn_domains'])})
    args.output.write_text(json.dumps(candidate, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('before_revision','candidate_revision','direct_count','vpn_count')}))
    print('Added domain suffixes:', len(report['added_domains']))


if __name__ == '__main__':
    main()
