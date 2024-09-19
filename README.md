# Stemoji

This discord bot allows you to use customize emojis that you put in the bot. It utilizes
the new application emoji features that supports up to 4000 custom emojis!

**(this is still in development babes)**

## Self-host setup
### Clone the repository
```
git clone https://github.com/InterStella0/stemoji
```
### Python
Install Python dependencies
```commandline
pip install -r requirements.txt
```
### Environment variable
Configure **default.env** and rename it to **.env**.

The description for each environment variable are described below.

|          VARIABLE           |  TYPE   |                           DESCRIPTION                            |
|:---------------------------:|:-------:|:----------------------------------------------------------------:|
|          BOT_TOKEN          | String  |                 Get it from discord API portal.                  |
|     TEXT_COMMAND_PREFIX     | String  |         This will be the prefix for your text commands.          |
| TEXT_COMMAND_PREFIX_MENTION | Boolean |      This will allow text commands to be used by mentions.       |
|   MESSAGE_CONTENT_INTENTS   | Boolean |          It allows prefix commands to work everywhere.           |
|       MEMBERS_INTENTS       | Boolean |   Allows your bot to have better profile mirroring experience    |
|          DATABASE           | String  |         Database choice, use 'sqlite' for simple setup.          |
|        DATABASE_DSN         | String  |                   Database connection string.                    |
|         OWNER_ONLY          | Boolean |            Disallow other people from using your bot.            |
|       MIRROR_PROFILE        | Boolean | Uses your profile picture and display name as the bot's profile. |
|       RETAIN_PROFILE        | Boolean |           Recover your bot's profile during shutdown.            |


## etc