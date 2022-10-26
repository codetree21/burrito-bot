#!/bin/sh

docker build --tag burrito-bot .

docker run --env SLACK_BOT_TOKEN --env SLACK_SIGNING_SECRET --env BURRITO_DB_USERNAME --env BURRITO_DB_PASSWORD -d -p 3000:3000 burrito-bot
