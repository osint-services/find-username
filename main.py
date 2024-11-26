import httpx
import logging

from fastapi import FastAPI
from http import HTTPStatus

from .database import *

# Set up logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)  # You can change to DEBUG or ERROR based on your needs

# Create console handler and set level to INFO
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)

# Create file handler to store logs
fh = logging.FileHandler('finder.log')
fh.setLevel(logging.INFO)

# Create formatter and add it to the handlers
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
fh.setFormatter(formatter)

# Add the handlers to the logger
logger.addHandler(ch)
logger.addHandler(fh)

app = FastAPI()
client = httpx.AsyncClient()

"""
Gets list of websites from WhatsMyName, this is used to search usernames
"""
def get_site_list() -> list[dict]:
    url = "https://raw.githubusercontent.com/WebBreacher/WhatsMyName/main/wmn-data.json"
    response = httpx.get(url)

    try:
        if response.status_code == HTTPStatus.OK:
            data = response.json()
            logger.info("Successfully retrieved site list from WhatsMyName")
            return data['sites'] # there is a schema provided by the repository which could be used for validation here
        else:
            logger.error(f"Failed to retrieve JSON. Status code: {response.status_code}")
            raise Exception(f"Failed to retrieve JSON. Status code: {response.status_code}")
    except Exception as e:
        logger.exception("Error while fetching site list", e)
        raise Exception(f"Failed to retrieve JSON. Error: {e}")

@app.on_event("startup")
async def boot():
    cursor = conn.cursor()
    logger.info('Building database tables...')
    # Create the tables
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS usernames_searched (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        search_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        uri_check TEXT NOT NULL,
        cat TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS username_correlations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username_id INTEGER,
        site_id INTEGER,
        found_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (username_id) REFERENCES usernames_searched(id),
        FOREIGN KEY (site_id) REFERENCES sites(id)
    );
    ''')
    conn.commit()

    logger.info('Ingesting website data...')

    try:
        sites = get_site_list()
        insert_sites(sites)
        logger.info(f"Successfully inserted {len(sites)} sites into the database.")
    except Exception as e:
        logger.error("Failed to ingest website data")
        logger.exception(e)


@app.get("/wmn/{username}")
async def get_username_data(username: str):
    if has_username_been_searched(username):
        logger.info(f"Username '{username}' has been previously searched.")
        sites = get_sites_by_username(username)
        return sites

    sites_found = []
    insert_username(username)
    logger.info(f"Started searching for username '{username}' on the sites.")

    sites = get_all_sites()
    for site_data in sites:
        site = site_data[2]
        try:
            url = site.format(account=username) # WhatsMyName uses `account` as formatter argument
            response = await client.head(url)
            if response.status_code == 200:
                insert_username_correlation(username, site_data)
                sites_found.append(site_data)
                logger.info(f"Username '{username}' found on site: {site}")
        except (httpx.ReadTimeout, httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadError, ValueError) as e:
            logger.warning(f"Error while checking site '{site}' for username '{username}': {e}")
            continue
        except Exception as e:
            logger.exception(f"Unexpected error while searching for username '{username}' on site '{site}'")
            raise e

    logger.info(f"Finished searching for username '{username}'. Found {len(sites_found)} sites.")
    return sites_found

