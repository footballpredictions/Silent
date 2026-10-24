"""Refresh a source-only whitelist catalog without altering active VPN routing."""
import argparse
import asyncio
import json
import logging

from app.services.whitelist_catalog import catalog_summary, load_catalog, refresh_catalog

logger = logging.getLogger(__name__)
INTERVAL_SECONDS = 6 * 60 * 60
RETRY_SECONDS = 15 * 60


async def whitelist_sources_loop():
    await asyncio.sleep(90)
    while True:
        delay = INTERVAL_SECONDS
        try:
            catalog = await asyncio.to_thread(refresh_catalog)
            summary = catalog_summary(catalog)
            logger.info('whitelist catalog: status=%s entries=%s quarantine=%s routing unchanged',
                        summary['status'], summary['entry_count'], summary['quarantine_count'])
            if summary['status'] != 'current':
                delay = RETRY_SECONDS
        except Exception as error:
            logger.warning('whitelist catalog refresh failed: %s; routing unchanged', type(error).__name__)
            delay = RETRY_SECONDS
        await asyncio.sleep(delay)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--once', action='store_true')
    arguments = parser.parse_args()
    if arguments.status:
        print(json.dumps(catalog_summary(load_catalog()), ensure_ascii=True))
    elif arguments.once:
        print(json.dumps(catalog_summary(refresh_catalog()), ensure_ascii=True))
    else:
        asyncio.run(whitelist_sources_loop())


if __name__ == '__main__':
    main()
