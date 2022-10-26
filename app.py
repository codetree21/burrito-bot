import os
# Use the package we installed
from collections import defaultdict

from slack_bolt import App
from pymongo import MongoClient
import pytz
from datetime import datetime
import re

# Initializes your app with your bot token and signing secret
app = App(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET")
)


class MongoDBClient:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            username = os.environ.get("BURRITO_DB_USERNAME")
            password = os.environ.get("BURRITO_DB_PASSWORD")
            cls._instance = MongoClient(
                f"mongodb+srv://{username}:{password}@codetree-burrito.xzklmhd.mongodb.net/?retryWrites=true&w=majority"
            )
        return cls._instance


def _get_burrito_map(burritos):
    mongo_client = MongoDBClient()

    db = mongo_client.prod
    user_db = db.user

    burrito_map = defaultdict(int)

    for burrito in burritos:
        mention_user_id = burrito["mention_user_id"]
        mention_username = user_db.find_one({"_id": mention_user_id})["profile"]["display_name"]
        burrito_map[mention_username] += 1

    return burrito_map


@app.event("app_home_opened")
def update_home_tab(event, client, logger):
    try:
        mongo_client = MongoDBClient()

        db = mongo_client.prod
        burrito_db = db.burrito

        burritos = burrito_db.find()

        burrito_map = _get_burrito_map(burritos)

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Burrito Dashboard* :tada:"
                }
            },
            {
                "type": "divider"
            },
        ]

        dashboard = [{
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{mention_username}: `{burrito_map[mention_username]}`"
            }
        } for mention_username in sorted(burrito_map, key=burrito_map.get, reverse=True)]

        blocks.extend(dashboard)

        client.views_publish(
            # the user that opened your app's app home
            user_id=event["user"],
            # the view object that appears in the app home
            view={
                "type": "home",
                "callback_id": "home_view",
                # body of the view
                "blocks": blocks
            }
        )

    except Exception as e:
        logger.error(f"Error publishing home tab: {e}")


def _get_user(slack_client, user_id):
    mongo_client = MongoDBClient()

    db = mongo_client.prod
    user = db.user

    result = slack_client.users_info(
        user=user_id,
    )

    user_data = result.get("user")

    user.replace_one(
        {"id": user_id},
        user_data,
        upsert=True,
    )

    user_object_id = user.find_one({
        "id": user_id,
    })["_id"]

    return user_object_id


def _validate_message(slack_client, channel_id, author_id, author_object_id, elements, today, tmrw):
    mention_user_ids = [
        p.get("user_id") for p in elements if p.get("type") == "user"
    ]

    mention_count = len(mention_user_ids)

    if mention_count != 1:
        slack_client.chat_postMessage(
            channel=channel_id,
            text=":burrito: 부리또 증정은 한 명에게 해야 합니다.",
        )

        return False

    mention_user_id = mention_user_ids[0]

    if author_id == mention_user_id:
        slack_client.chat_postMessage(
            channel=channel_id,
            text=":burrito: 자신에게 부리또를 증정할 수는 없습니다.",
        )

        return False

    mongo_client = MongoDBClient()

    db = mongo_client.prod
    burrito_db = db.burrito

    burrito_count = burrito_db.count_documents({
        "created_at": {
            "$gte": today,
            "$lte": tmrw,
        },
        "author_id": author_object_id,
    })

    if burrito_count > 3:
        slack_client.chat_postMessage(
            channel=channel_id,
            text=":burrito: 하루에 부리또는 총 3개만 선물할 수 있습니다.",
        )

        return False

    return _get_user(slack_client, mention_user_id)


@app.event("message")
def add_burritos(event, client, logger):
    try:
        elements = event.get("blocks")[0].get("elements")[0].get("elements")

        if not sum(1 for element in elements if element.get("type") == "emoji" and element.get("name") == "burrito"):
            return

        mongo_client = MongoDBClient()

        db = mongo_client.prod
        burrito_db = db.burrito

        elements = event.get("blocks")[0].get("elements")[0].get("elements")
        channel_id = event.get("channel")

        author_id = event["user"]

        author_object_id = _get_user(client, author_id)

        created_at = datetime.utcnow()

        tz = pytz.timezone("Asia/Seoul")

        today = datetime.now(tz).replace(
            hour=0, minute=0, second=0
        )

        tmrw = datetime.now(tz).replace(
            hour=23, minute=59, second=59
        )

        mention_object_id = _validate_message(
            client, channel_id, author_id, author_object_id, elements, today, tmrw
        )

        if not mention_object_id:
            return

        text = event.get("text")

        message = re.sub("<.+>|:burrito:", "", text).strip()

        burrito_db.insert_one(
            {
                "created_at": created_at,
                "mention_user_id": mention_object_id,
                "author_id": author_object_id,
                "message": message
            }
        )

        burritos = burrito_db.find({
            "created_at": {
                "$gte": today,
                "$lte": tmrw,
            }
        })

        burrito_map = _get_burrito_map(burritos)

        text = ":burrito: 부리또를 성공적으로 주셨습니다.:burrito:\n\n*오늘의 부리또*\n\n"

        for mention_username in sorted(burrito_map, key=burrito_map.get, reverse=True):
            text += f"{mention_username}: `{burrito_map[mention_username]}`\n"

        client.chat_postMessage(
            channel=channel_id,
            text=text,
        )

    except Exception as e:
        logger.error(e)


# Start your app
if __name__ == "__main__":
    app.start(port=int(os.environ.get("PORT", 3000)))


