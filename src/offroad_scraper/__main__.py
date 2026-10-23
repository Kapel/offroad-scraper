from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

import structlog

from offroad_scraper.config import Settings, load_sites
from offroad_scraper.logging_conf import configure_logging
from offroad_scraper.models import Trip, is_recent

logger = structlog.get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="offroad-scraper",
        description="Scrape offroad trips and publish an ICS calendar.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("scrape", help="Fetch trip listings, extract trips, rebuild the ICS.")
    subparsers.add_parser("serve", help="Serve the ICS file over HTTP.")
    return parser


def run_scrape(settings: Settings) -> int:
    import openai

    from offroad_scraper.calendar_builder import write_calendar_atomic
    from offroad_scraper.cost_estimator import CostEstimator
    from offroad_scraper.extractor import Extractor
    from offroad_scraper.http_client import HttpClient, HttpClientError
    from offroad_scraper.link_extractor import extract_candidate_urls, parse_rss_links
    from offroad_scraper.store import StoreError, TripStore

    if settings.deepseek_api_key is None:
        logger.error("DEEPSEEK_API_KEY is required for the 'scrape' command")
        return 1

    sites = load_sites(settings.sites_file)
    if not sites:
        logger.warning("no sites loaded", path=str(settings.sites_file))

    cutoff = date.today() - timedelta(days=settings.retention_days)

    client = HttpClient(
        timeout_seconds=settings.scrape_timeout_seconds,
        max_bytes=settings.scrape_max_bytes,
        user_agent=settings.scrape_user_agent,
    )
    extractor = Extractor(settings)
    cost_estimator = CostEstimator(settings)
    store = TripStore(settings.output_dir)

    def process_page(site_name: str, html: str, detail_url: str | None, language: str) -> int:
        try:
            trips = extractor.extract(site_name, html, language)
        except openai.OpenAIError as exc:
            logger.error("fatal llm error, aborting run", site=site_name, error=str(exc))
            raise
        if detail_url is not None:
            trips = [_ensure_url(trip, detail_url) for trip in trips]
        trips = [trip.model_copy(update={"provider": site_name}) for trip in trips]
        trips = [trip for trip in trips if is_recent(trip, cutoff)]
        trips = cost_estimator.estimate(trips)
        try:
            added = store.merge(trips)
        except StoreError as exc:
            logger.error("failed to persist trips, aborting run", error=str(exc))
            raise
        logger.info("merged trips", site=site_name, found=len(trips), added=added)
        return len(trips)

    def crawl_detail_pages(site_name: str, urls: list[str], language: str) -> int:
        total = 0
        for detail_url in urls:
            try:
                detail_html = client.fetch(detail_url)
            except HttpClientError as exc:
                logger.error("detail fetch failed", site=site_name, url=detail_url, error=str(exc))
                continue
            total += process_page(site_name, detail_html, detail_url, language)
        return total

    total_extracted = 0
    for site in sites:
        if site.mode == "list" and site.feed_url is not None:
            logger.info("scraping site via feed", site=site.name, feed_url=site.feed_url)
            try:
                feed_xml = client.fetch(site.feed_url)
            except HttpClientError as exc:
                logger.error("feed fetch failed", site=site.name, error=str(exc))
                continue
            urls = parse_rss_links(
                feed_xml,
                site.feed_url,
                exclude_paths=site.exclude_paths,
                max_urls=site.max_detail_pages,
            )
            logger.info("found rss detail pages", site=site.name, count=len(urls))
            try:
                total_extracted += crawl_detail_pages(site.name, urls, site.language)
            except (openai.OpenAIError, StoreError):
                return 1
            continue

        logger.info("scraping site", site=site.name, url=site.url)
        try:
            html = client.fetch(site.url)
        except HttpClientError as exc:
            logger.error("fetch failed", site=site.name, error=str(exc))
            continue

        if site.mode == "list":
            urls = extract_candidate_urls(
                html,
                site.url,
                exclude_paths=site.exclude_paths,
                max_urls=site.max_detail_pages,
            )
            logger.info("found candidate detail pages", site=site.name, count=len(urls))
            try:
                total_extracted += crawl_detail_pages(site.name, urls, site.language)
            except (openai.OpenAIError, StoreError):
                return 1
        else:
            try:
                total_extracted += process_page(site.name, html, None, site.language)
            except (openai.OpenAIError, StoreError):
                return 1

    try:
        store.prune(cutoff)
        all_trips = store.all_trips()
    except StoreError as exc:
        logger.error("failed to read trips store, aborting run", error=str(exc))
        return 1

    signature = store.content_signature()
    if signature == store.load_signature():
        logger.info("calendar unchanged, skipping rebuild", count=len(all_trips))
        return 0

    path = write_calendar_atomic(settings.output_dir, all_trips)
    store.save_signature(signature)
    logger.info("wrote calendar", path=str(path), count=len(all_trips), extracted=total_extracted)
    return 0


def _ensure_url(trip: Trip, detail_url: str) -> Trip:
    if trip.url is None:
        return trip.model_copy(update={"url": detail_url})
    return trip


def run_serve(settings: Settings) -> int:
    import uvicorn

    from offroad_scraper.server import create_app

    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, log_config=None, access_log=False)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings()
    configure_logging(settings.log_level)
    if args.command == "scrape":
        return run_scrape(settings)
    if args.command == "serve":
        return run_serve(settings)
    return 1


if __name__ == "__main__":
    sys.exit(main())
