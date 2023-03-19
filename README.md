# Discord IoT bot
The ability for you to control your Tuya Smart devices from a discord
bot. This is a working prototype suited if you have Tuya Smart Switches.

This are not designed to be used in production. Better for personal use.

## Usage
### Cloning & install
You need to install Python. After that, clone this repository and 
install the requirements.
```bash
git clone https://github.com/InterStella0/discord-iot-bot.git
cd discord-iot-bot
pip install -r requirements.txt
```

### Database
You will need to create a database with [PostgreSQL](https://www.postgresql.org). Simply copy
paste the scripts in `script.sql` into the command prompt.


### Credentials
Once that is successful. You would need to fill in your
related credential into `default-settings.py`.
**Please rename this to `settings.py`.**


### Running
Run your bot
```bash
python main.py
```

Finally, invite your bot into your discord server. And type
`?uwu sync` into discord.

This will create related slash command into discord so you
can use it with slash commands.