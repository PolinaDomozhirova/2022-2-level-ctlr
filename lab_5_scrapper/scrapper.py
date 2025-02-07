"""
Crawler implementation
"""
import datetime
import json
import re
import shutil
from pathlib import Path
from typing import Pattern, Union
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from core_utils.article.article import Article
from core_utils.article.io import to_meta, to_raw
from core_utils.config_dto import ConfigDTO
from core_utils.constants import (ASSETS_PATH, CRAWLER_CONFIG_PATH,
                                  NUM_ARTICLES_UPPER_LIMIT,
                                  TIMEOUT_LOWER_LIMIT, TIMEOUT_UPPER_LIMIT)


class IncorrectSeedURLError(Exception):
    """
    Raised when the seed URL does not match the
    standard pattern or does not correspond to the target website
    """


class NumberOfArticlesOutOfRangeError(Exception):
    """
    Raised when the total number of articles is out of range from 1 to 150
    """


class IncorrectNumberOfArticlesError(Exception):
    """
    Raised when the total number of articles to parse is not an integer
    """


class IncorrectHeadersError(Exception):
    """
    Raised when headers are not in the form of a dictionary
    """


class IncorrectEncodingError(Exception):
    """
    Raised when the encoding is not specified as a string
    """


class IncorrectTimeoutError(Exception):
    """
    Raised when the timeout value is not a positive integer less than 60
    """


class IncorrectVerifyError(Exception):
    """
    Raised when the verify certificate value is not either True or False
    """



class Config:
    """
    Unpacks and validates configurations
    """
    def __init__(self, path_to_config: Path) -> None:
        """
        Initializes an instance of the Config class
        """
        self.path_to_config = path_to_config
        self.config_data = self._extract_config_content()
        self._seed_urls = self.config_data.seed_urls
        self._num_articles = self.config_data.total_articles
        self._headers = self.config_data.headers
        self._encoding = self.config_data.encoding
        self._timeout = self.config_data.timeout
        self._should_verify_certificate = self.config_data.should_verify_certificate
        self._headless_mode = self.config_data.headless_mode

        self._validate_config_content()

    def _extract_config_content(self) -> ConfigDTO:
        """
        Returns config values
        """
        with open(self.path_to_config, 'r', encoding='utf-8') as file:
            config = json.load(file)
        return ConfigDTO(**config)


    def _validate_config_content(self) -> None:
        """
        Ensure configuration parameters
        are not corrupt
        """
        if not isinstance(self._seed_urls, list) or not all(isinstance(url, str)
                for url in self._seed_urls):
            raise IncorrectSeedURLError("Invalid value for seed_urls in configuration file")
        for seed_url in self._seed_urls:
            if not re.match(r'^https?://(www.)?', seed_url):
                raise IncorrectSeedURLError(
    "Invalid seed URL. Seed URLs must start with 'http://'"
    " or 'https://' and may contain 'www.'"
    )

        if not isinstance(self._num_articles, int) \
                or  self._num_articles < 1:
            raise IncorrectNumberOfArticlesError(
                "Invalid value for total_articles_to_find_and_parse in configuration file")
        if  self._num_articles > NUM_ARTICLES_UPPER_LIMIT:
            raise NumberOfArticlesOutOfRangeError(
                "Invalid value for total_articles_to_find_and_parse in configuration file")

        if not isinstance(self._headers, dict):
            raise IncorrectHeadersError("Invalid value for headers in configuration file")

        if not isinstance(self._encoding, str):
            raise IncorrectEncodingError("Invalid value for encoding in configuration file")

        if not isinstance(self._timeout, int) or self._timeout <= TIMEOUT_LOWER_LIMIT \
                or self._timeout >= TIMEOUT_UPPER_LIMIT:
            raise IncorrectTimeoutError(
                "Invalid value for timeout in configuration file"
                )

        if not isinstance(self._should_verify_certificate, bool):
            raise IncorrectVerifyError(
        "Invalid value for should_verify_certificate in configuration file"
        )

        if not isinstance(self._headless_mode, bool):
            raise IncorrectVerifyError(
        "Invalid value for headless_mode in configuration file"
        )


    def get_seed_urls(self) -> list[str]:
        """
        Retrieve seed urls
        """
        return self._seed_urls

    def get_num_articles(self) -> int:
        """
        Retrieve total number of articles to scrape
        """
        return self._num_articles


    def get_headers(self) -> dict[str, str]:
        """
        Retrieve headers to use during requesting
        """
        return self._headers


    def get_encoding(self) -> str:
        """
        Retrieve encoding to use during parsing
        """
        return self._encoding

    def get_timeout(self) -> int:
        """
        Retrieve number of seconds to wait for response
        """
        return self._timeout

    def get_verify_certificate(self) -> bool:
        """
        Retrieve whether to verify certificate
        """
        return self._should_verify_certificate

    def get_headless_mode(self) -> bool:
        """
        Retrieve whether to use headless mode
        """
        return self._headless_mode

def make_request(url: str, config: Config) -> requests.models.Response:
    """
    Delivers a response from a request
    with given configuration
    """
    headers = config.get_headers()
    timeout = config.get_timeout()
    verify = config.get_verify_certificate()
    response = requests.get(url, headers=headers, timeout=timeout, verify=verify)
    response.encoding = config.get_encoding()

    return response


class Crawler:
    """
    Crawler implementation
    """

    url_pattern: Union[Pattern, str]

    def __init__(self, config: Config) -> None:
        """
        Initializes an instance of the Crawler class
        """
        self.seed_urls = config.get_seed_urls()
        self.config = config
        self.urls = []

    def _extract_url(self, article_bs: BeautifulSoup) -> str:
        """
        Finds and retrieves URL from HTML
        """
        href = article_bs.get('href')
        if href:
            full_url = urljoin('https://dzer.ru/', str(href))
            if not urlparse(full_url).scheme:
                full_url = "http://" + full_url
            return full_url
        return ''



    def find_articles(self) -> None:
        """
        Finds articles
        """
        while len(self.urls) < self.config.get_num_articles():
            for seed_url in self.seed_urls:
                response = make_request(seed_url, self.config)
                main_bs = BeautifulSoup(response.text, 'html.parser')
                for elem in main_bs.find_all('a', class_=lambda value: value
                    and ('mininews' in value or 'midinews' in value)):
                    if len(self.urls) >= self.config.get_num_articles():
                        return
                    article_url = self._extract_url(elem)
                    if not article_url or article_url in self.urls:
                        continue
                    self.urls.append(article_url)


    def get_search_urls(self) -> list:
        """
        Returns seed_urls param
        """
        return self.seed_urls



class HTMLParser:
    """
    ArticleParser implementation
    """

    def __init__(self, full_url: str, article_id: int, config: Config) -> None:
        """
        Initializes an instance of the HTMLParser class
        """
        self.article_url = full_url
        self.article_id = article_id
        self.config = config
        self.article = Article(self.article_url, self.article_id)

    def _fill_article_with_text(self, article_soup: BeautifulSoup) -> None:
        """
        Finds text of article
        """
        text_elements = article_soup.find_all("div", class_='article__paragraph')
        text_list = [element.get_text(strip=True) for element in text_elements]
        text = "\n".join(text_list)
        self.article.text = text


    def _fill_article_with_meta_information(self, article_soup: BeautifulSoup) -> None:
        """
        Finds meta information of article
        """
        title_tag = article_soup.find('h1', {'class': 'article__title'})
        if title_tag is not None:
            title = title_tag.get_text(strip=True)
            self.article.title = title
        else:
            self.article.title = "NOT FOUND"

        author_tag = article_soup.select('p.article__prepared, b')
        authors = []
        if author_tag:
            for tag in author_tag:
                text = tag.get_text(strip=True)
                if re.search(r"Наш\s+корр\.", text):
                    text = re.search(r"корр\.", text).group(0)
                if '\r\n' in text:
                    text = text.replace('\r\n', ' ')
                author_words = text.split(' ')
                last_name = author_words[-1]
                authors.append(last_name)
        else:
            authors = ["NOT FOUND"]
        self.article.author = authors


        topic_tag = article_soup.find('div', {'class': 'article__category'}).find_all('a')[0]
        topic = topic_tag.get_text(strip=True)
        self.article.topics = topic


        date_tag = article_soup.find('div', {'class': 'article__date'})
        date_str = date_tag.get_text(strip=True)
        date = self.unify_date_format(date_str)
        self.article.date = date

    def unify_date_format(self, date_str: str) -> datetime.datetime:
        """
        Unifies date format
        """
        months = {
            "января": "january",
            "февраля": "february",
            "марта": "march",
            "апреля": "april",
            "мая": "may",
            "июня": "june",
            "июля": "july",
            "августа": "august",
            "сентября": "september",
            "октября": "october",
            "ноября": "november",
            "декабря": "december"
        }
        for rus_month, en_month in months.items():
            date_str = date_str.replace(rus_month, en_month)
        if 'сегодня' in date_str:
            today = datetime.datetime.now()
            date_str = date_str.replace('сегодня', today.strftime('%d %B %Y'))
        elif 'вчера' in date_str:
            yesterday = datetime.datetime.now() - datetime.timedelta(days=1)
            date_str = date_str.replace('вчера', yesterday.strftime('%d %B %Y'))
        elif 'назад' in date_str:
            match = re.match(r"(\d+) (\w+)", date_str)
            if match:
                num, unit = match.groups()
                delta = None
                if 'минут' in unit:
                    delta = datetime.timedelta(minutes=int(num))
                elif 'час' in unit:
                    delta = datetime.timedelta(hours=int(num))
                elif 'день' in unit:
                    delta = datetime.timedelta(days=int(num))
                if delta is not None:
                    return datetime.datetime.now() - delta
        regular = re.match(r"\d{1,2} [A-Za-z]+ \d{4}, \d{1,2}:\d{2}", date_str)
        if regular:
            return datetime.datetime.strptime(date_str, '%d %B %Y, %H:%M')
        return datetime.datetime.strptime(date_str, '%H:%M, %d %B %Y')




    def parse(self) -> Union[Article, bool, list]:
        """
        Parses each article
        """
        response = make_request(self.article_url, self.config)
        article_soup = BeautifulSoup(response.text, 'html.parser')
        self._fill_article_with_text(article_soup)
        self._fill_article_with_meta_information(article_soup)
        return self.article





def prepare_environment(base_path: Union[Path, str]) -> None:
    """
    Creates ASSETS_PATH folder if no created and removes existing folder
    """
    if base_path.exists():
        shutil.rmtree(base_path)
    base_path.mkdir(parents=True)


def main() -> None:
    """
    Entrypoint for scrapper module
    """
    config = Config(path_to_config=CRAWLER_CONFIG_PATH)
    prepare_environment(ASSETS_PATH)

    crawler = Crawler(config=config)
    crawler.find_articles()

    for i, url in enumerate(crawler.urls, start=1):
        parser = HTMLParser(full_url=url, article_id=i, config=config)
        article = parser.parse()

        if article is not None and isinstance(article, Article):
            to_raw(article)
            to_meta(article)



if __name__ == "__main__":
    main()
