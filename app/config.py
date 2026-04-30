import os
from dotenv import load_dotenv
load_dotenv()

OPENAI_API_KEY = os.getenv("OPEN_AI_TOKEN")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
MS_LOGIN = os.getenv("MC_LOGIN")
MS_PASSWORD = os.getenv("MC_PASSWORD")

MS_BASE_URL = "https://api.moysklad.ru/api/remap/1.2"
MS_AUTH = (MS_LOGIN, MS_PASSWORD)

DEFAULT_ORGANIZATION_ACCOUNT_META = {
    "href": "https://api.moysklad.ru/api/remap/1.2/entity/organization/8ff883ac-672f-11e7-7a6c-d2a90012b2eb/accounts/8ff887ae-672f-11e7-7a6c-d2a90012b2ec",
    "type": "account",
    "mediaType": "application/json",
}

DEFAULT_GROUP_META = {
    "href": "https://api.moysklad.ru/api/remap/1.2/entity/group/b4e07c18-4052-11ea-0a80-006f000a08c3",
    "metadataHref": "https://api.moysklad.ru/api/remap/1.2/entity/group/metadata",
    "type": "group",
    "mediaType": "application/json",
}