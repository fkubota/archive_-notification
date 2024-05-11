import argparse
import datetime
import os
import re
import time
import urllib.parse
import warnings
from dataclasses import dataclass

from make_slide import make_slides
import arxiv
from openai import OpenAI

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from io import BytesIO

import yaml
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from webdriver_manager.firefox import GeckoDriverManager
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.common.by import By
from pathlib import Path
import feedparser
import datetime

# setting
warnings.filterwarnings("ignore")

@dataclass
class Result:
    score: float = 0.0
    hit_keywords: list = None
    source: type = None
    res: dict = None
    abst_jp: str = None


PROMPT = """与えられた論文の要点をまとめ、以下の項目で日本語で出力せよ。それぞれの項目は最大でも180文字以内に要約せよ。

論文名:タイトルの日本語訳
キーワード:この論文のキーワード
課題:この論文が解決する課題
手法:この論文が提案する手法
結果:提案手法によって得られた結果

さらに要約内に登場する主要な専門用語について、高校生にもわかるような説明を付け加えよ。日本語だけでなく、翻訳元の英語表記も添えよ。それぞれの用語について、説明の終わりにのみ改行記号を用いよ。
"""
BASE_DIR=Path("./files")
CHANNEL_ID = "C03KGQE0FT6"


def calc_score(abst: str, keywords: dict):
    sum_score = 0.0
    hit_kwd_list = []

    for word in keywords.keys():
        score = keywords[word]
        if (word in abst) or (not word.isupper() and word.lower() in abst.lower()):
            sum_score += score
            hit_kwd_list.append(word)
    return sum_score, hit_kwd_list


def get_text_from_driver(driver) -> str:
    try:
        elem = driver.find_element(by=By.XPATH, value='//*[@id="textareasContainer"]/div[3]/section/div[1]/d-textarea/div')
    except NoSuchElementException as e:
        print(e)
        return None
    text = elem.get_attribute("textContent")
    return text

def get_translated_text(from_lang: str, to_lang: str, from_text: str, driver) -> str:
    sleep_time = 1
    from_text = urllib.parse.quote(from_text)
    url = "https://www.deepl.com/translator#" \
        + from_lang + "/" + to_lang + "/" + from_text

    driver.get(url)
    driver.implicitly_wait(10)

    for i in range(30):
        time.sleep(sleep_time)
        to_text = get_text_from_driver(driver)
        if to_text:
            break
    if to_text is None:
        return urllib.parse.unquote(from_text)
    return to_text


def search_keyword(
        driver, articles: list, keywords: dict, score_threshold: float
        ):
    results = []
    for article in articles:
        abstract = article.summary.replace("\n", " ")
        score, hit_keywords = calc_score(abstract, keywords)
        if score < score_threshold:
            continue
        abstract_trans = get_translated_text("en", "ja", abstract, driver)

        article.authors = ", ".join([author.name for author in article.authors])
        result = Result(score=score, hit_keywords=hit_keywords, source="arxiv", res=article, abst_jp=abstract_trans)
        results.append(result)
    return results


def ecs_login(driver, url, ecs_info):
    driver.get(url)
    try:
        driver.find_element(by=By.XPATH, value='//*[@id="IdButton1"]/input[3]').click()
        driver.find_element(by=By.XPATH, value='//*[@id="username"]').send_keys(ecs_info[0])
        driver.find_element(by=By.XPATH, value='//*[@id="password"]').send_keys(ecs_info[1])
        driver.find_element(by=By.XPATH, value='/html/body/div/div/div/div/form/div[4]/button').click()
        try:
            driver.find_element(by=By.XPATH, value='//input[@type="submit"]').click()
        except:
            pass
    except:
        pass
    time.sleep(2)
    print(driver.page_source)


def parse_iop_rss(driver, rss_url_list: list, keywords: dict, score_threshold: float, ecs_info: list[str, str]):
    results = []
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    for i, url in enumerate(rss_url_list):
        if i==0:
            ecs_login(driver, url, ecs_info)
        else:
            driver.get(url)
            time.sleep(2)

        d = feedparser.parse(driver.page_source)
        print(f"{len(d['entries'])} articles are found in RSS feed.")
        for entry in d["entries"]:
            if time.strftime("%Y-%m-%d", entry["updated_parsed"]) != yesterday:
                print(f"{entry['title']} is updated at {entry['updated']}.")
                continue
            abstract = entry["summary"].replace("\n", " ")
            score, hit_keywords = calc_score(abstract, keywords)
            if score < score_threshold:
                print(f"Score of {entry['title']} is {score}.")
                continue
            entry["authors"] = entry["authors"][0]["name"]
            abstract_trans = get_translated_text("en", "ja", abstract, driver)
            result = Result(score=score, hit_keywords=hit_keywords, source="iop", res=entry, abst_jp=abstract_trans)
            results.append(result)

    return results



def parse_elsevier_rss(driver, rss_url_list: list, keywords: dict, score_threshold: float):
    results = []
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    for i, url in enumerate(rss_url_list):
        d = feedparser.parse(url)
        print(f"{len(d['entries'])} articles are found in RSS feed.")
        for entry in d["entries"]:
            try:
                if time.strftime("%Y-%m-%d", entry["updated_parsed"]) != yesterday:
                    # print(f"{entry['title']} is updated at {entry['updated']}.")
                    continue
                abstract = entry["summary"].removeprefix('<div class="abstract"><p>').removesuffix('</p></div>')
                entry["summary"] = abstract
                entry["doi"] = entry["prism_doi"]
                entry["pdf_url"] = ""
                score, hit_keywords = calc_score(abstract, keywords)
                if score < score_threshold:
                    print(f"Score of {entry['title']} is {score}.")
                    continue
                abstract_trans = get_translated_text("en", "ja", abstract, driver)
                
                entry["authors"] = ", ".join([author["name"] for author in entry["authors"]])
                entry["link"] = entry["id"]
                entry["updated"] = d["updated"]
                entry["updated_parsed"] = d["updated_parsed"]
                result = Result(score=score, hit_keywords=hit_keywords, source="cambridge", res=entry, abst_jp=abstract_trans)
                results.append(result)

            except Exception as e:
                print(e)
                continue
                
    return results


def parse_cambridge_rss(driver, rss_url_list: list, keywords: dict, score_threshold: float):
    results = []
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    for i, url in enumerate(rss_url_list):
        if i==0:
            ecs_login(driver, url, ecs_info)
        else:
            driver.get(url)
            time.sleep(2)

        d = feedparser.parse(driver.page_source)
        print(f"{len(d['entries'])} articles are found in RSS feed.")
        for entry in d["entries"]:
            if time.strftime("%Y-%m-%d", entry["updated_parsed"]) != yesterday:
                print(f"{entry['title']} is updated at {entry['updated']}.")
                continue
            abstract = entry["summary"].replace("\n", " ")
            score, hit_keywords = calc_score(abstract, keywords)
            if score < score_threshold:
                print(f"Score of {entry['title']} is {score}.")
                continue
            entry["authors"] = entry["authors"][0]["name"]
            abstract_trans = get_translated_text("en", "ja", abstract, driver)
            result = Result(score=score, hit_keywords=hit_keywords, source="iop", res=entry, abst_jp=abstract_trans)
            results.append(result)

    return results


def get_summary(result, client):
    res = result.res
    if result.source == "arxiv":
        title = res.title.replace("\n ", "")
        body = res.summary.replace("\n", " ")
    else:
        title = res["title"].replace("\n ", "")
        body = res["summary"].replace("\n", " ")

    text = f"title: {title}\nbody: {body}"
    response = client.chat.completions.create(
    model="gpt-4-turbo",
    messages=[
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": text}
    ],
    temperature=0.25)
    summary = response.choices[0].message.content
    summary_dict = {}
    summary_dict["terminology"] = []
    i_result = -1
    for i, b in enumerate(summary.split("\n")):
        if b.startswith("論文名"):
            summary_dict["title_jp"] = b[4:].lstrip()
        if b.startswith("キーワード"):
            summary_dict["keywords"] = b[6:].lstrip()
        if b.startswith("課題"):
            summary_dict["problem"] = b[3:].lstrip()
        if b.startswith("手法"):
            summary_dict["method"] = b[3:].lstrip()
        if b.startswith("結果"):
            summary_dict["result"] = b[3:].lstrip()
            i_result = i
    if i_result != -1:
        for b in summary.split("\n")[i_result+1:]:
            b.replace("`", "")
            summary_dict["terminology"].append(b)

    if result.source == "arxiv":
        summary_dict["title"]= res.title
        summary_dict["id"] = res.get_short_id().replace(".", "_")
        summary_dict["date"] = res.published.strftime("%Y-%m-%d %H:%M:%S")
        summary_dict["authors"] = res.authors
        summary_dict["year"] = str(res.published.year)
        summary_dict["entry_id"] = str(res.entry_id)
        summary_dict["primary_category"] = str(res.primary_category)
        summary_dict["categories"] = res.categories
        summary_dict["journal_ref"] = res.journal_ref
        summary_dict["pdf_url"] = res.pdf_url
        summary_dict["doi"]= res.doi
        summary_dict["abstract"] = body
    else:
        summary_dict["title"]= res["title"]
        summary_dict["abstract"] = body
        summary_dict["year"] = str(res["updated_parsed"].tm_year)
        summary_dict["date"] = time.strftime("%Y-%m-%d %H:%M:%S", res["updated_parsed"])
        summary_dict["entry_id"] = str(res["link"])
        summary_dict["authors"] = res["authors"]
        if result.source == "iop":
            summary_dict["id"] = "_".join(Path(res["id"]).parts[-2:])
            summary_dict["pdf_url"] = res["iop_pdf"]
            summary_dict["doi"]= res["prism_doi"]
        elif result.source == "elsevier":
            summary_dict["id"] = Path(res["id"]).parts[-1]
            summary_dict["pdf_url"] = res["pdf_url"]
            summary_dict["doi"]= res["doi"]
        elif result.source == "elsevier":
            summary_dict["id"] = Path(res["doi"]).parts[-1]
            summary_dict["pdf_url"] = res["pdf_url"]
            summary_dict["doi"]= res["doi"]
        else:
            print("Unknown source.")

    return summary_dict


def send2app(text: str, slack_token: str, file: str=None, ts: str=None) -> None:
    if slack_token is not None:
        client = WebClient(token=slack_token)
        if file is None:
            try:
                new_message = client.chat_postMessage(
                    channel=CHANNEL_ID,
                    text=text,
                    thread_ts=ts,
                )
            except SlackApiError as e:
                new_message = client.chat_postMessage(
                    channel=CHANNEL_ID,
                    text=text,
                )
            return new_message["ts"]
        else:
            print(file)
            with open(file, "rb") as f:
                try:
                    new_file = client.files_upload(
                        channels=CHANNEL_ID,
                        file=BytesIO(f.read()),
                        filename=file.name,
                        filetype="pdf",
                        initial_comment=text,
                        thread_ts=ts,
                    )

                except SlackApiError as e:
                    new_file = client.files_upload(
                        channels=CHANNEL_ID,
                        file=BytesIO(f.read()),
                        filename=file.name,
                        filetype="pdf",
                        initial_comment=text,
                    )
            return None


def notify(results: list, slack_token: str, openai_api: str) -> None:
    star = "*"*80
    today = datetime.date.today()
    n_articles = len(results)
    text = f"{star}\n \t \t {today}\tnum of articles = {n_articles}\n{star}"
    ts = send2app(text, slack_token)
    if openai_api is not None:
        client = OpenAI(api_key=openai_api)
    else:
        client = None

    for result in sorted(results, reverse=True, key=lambda x: x.score):
        if result.source == "arxiv":
            url = result.res.entry_id
            title = result.res.title.replace("\n ", "")
            abstract_en = result.res.summary.replace("\n", " ").replace(". ", ". \n>")
            authors = result.res.authors
        else:
            url = result.res["link"]
            title = result.res["title"].replace("\n ", "")
            abstract_en = result.res["summary"].replace("\n", " ").replace(". ", ". \n>")
            authors = result.res["authors"]
        word = result.hit_keywords
        score = result.score
        abstract = result.abst_jp.replace("。", "。\n>")
        if abstract[-1] == "\n>":
            abstract = abstract.rstrip("\n>")

        text = f"\n Score: `{score}`"\
               f"\n Hit keywords: `{word}`"\
               f"\n URL: {url}"\
               f"\n Title: {title}"\
               f"\n Authors: {authors}"\
               f"\n Abstract:"\
               f"\n>{abstract}"\
               f"\n Original:"\
               f"\n>{abstract_en}"\
               f"\n {star}"

        file = None
        if client:
            try:
                summary_dict = get_summary(result, client)
                summary_dict["abst_jp"] = result.abst_jp
                id = summary_dict["id"]
                dirpath = BASE_DIR/id
                dirpath.mkdir(parents=True, exist_ok=True)
                pdf = f"{id}.pdf"
                if result.source == "arxiv":
                    result.res.download_pdf(dirpath=str(dirpath), filename=pdf)
                    summary_dict["pdf"] = str(dirpath/pdf)
                else:
                    print("Downloading pdf file should be done manually.")
                    summary_dict["pdf"] = None

                file = make_slides(dirpath, id, summary_dict)
            except Exception as e:
                print(e)
        send2app(text, slack_token, file, ts=ts)

def get_config():
    file_abs_path = os.path.abspath(__file__)
    file_dir = os.path.dirname(file_abs_path)
    config_path = f"{file_dir}/../config.yaml"
    with open(config_path, "r", encoding="utf-8") as yml:
        config = yaml.safe_load(yml)
    return config


def main():
    # debug用
    parser = argparse.ArgumentParser()
    parser.add_argument("--slack_token", default=None)
    parser.add_argument("--openai_api", default=None)
    parser.add_argument("--ecs_id", default=None)
    parser.add_argument("--ecs_password", default=None)
    args = parser.parse_args()

    config = get_config()
    subject = config["subject"]
    keywords = config["keywords"]
    score_threshold = float(config["score_threshold"])
    iop_rss_url = config.get("iop_rss_url", [])
    elsevier_rss_url = config.get("elsevier_rss_url", [])
    ecs_id = os.getenv("ECS_ID") or args.ecs_id
    ecs_pass = os.getenv("ECS_PASSWORD") or args.ecs_password

    options = webdriver.FirefoxOptions()
    options.add_argument("-headless")
    firefox_profile = webdriver.firefox.firefox_profile.FirefoxProfile()
    firefox_profile.set_preference("browser.privatebrowsing.autostart", True)
    options.profile = firefox_profile
    driver = webdriver.Firefox(service=Service(GeckoDriverManager().install()), options=options)
    driver.implicitly_wait(10)

    day_before_yesterday = datetime.datetime.today() - datetime.timedelta(days=2)
    day_before_yesterday_str = day_before_yesterday.strftime("%Y%m%d")
    arxiv_query = f"({subject}) AND " \
                  f"submittedDate:" \
                  f"[{day_before_yesterday_str}000000 TO {day_before_yesterday_str}235959]"
    articles = arxiv.Search(query=arxiv_query,
                           max_results=1000,
                           sort_by = arxiv.SortCriterion.SubmittedDate).results()
    articles = list(articles)
    results = []
    results_arxiv = search_keyword(driver, articles, keywords, score_threshold)
    results.extend(results_arxiv)
    results_iop = parse_iop_rss(driver, iop_rss_url, keywords, score_threshold, ecs_info=[ecs_id, ecs_pass])
    results.extend(results_iop)
    results_elsevier = parse_elsevier_rss(driver, elsevier_rss_url, keywords, score_threshold)
    results.extend(results_elsevier)

    driver.quit()

    slack_token = os.getenv("SLACK_BOT_TOKEN") or args.slack_token
    openai_api = os.getenv("OPENAI_API") or args.openai_api
    notify(results, slack_token, openai_api)


if __name__ == "__main__":
    main()
