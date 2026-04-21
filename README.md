# PumpPrices
Display's the current prices on Fuel (Diesel/Unleaded) within the radius you set and displays the cheapest. 

You can also enable notifications which inform you if any price hike/decrease. At present it supports the following

***IRC*** - You can enable/disable via fuel.conf - Only been tested using plain text 6667 **fully** IPv6 supported. 

***Telegram*** - You can enable/disable via fuel.conf. I've tested this, and works without any problems.

# What do I need?
currently: 
- A raspberry pi. The zero W works fine. The pi needs network one way or another. 
- A display adapter. **pimoroni inkyphat** https://shop.pimoroni.com/?q=inkyphat
- An sd card (obviously) - 4GB works fine. Raspbian buster LITE version uses only about half of that. No need for any more.  

# Preparing the pi
This is actually more of a tutorial on what I've found to be the best way to just set up a pi to run arbitrary code without the hassle of a mouse keyboard and monitor. It's the path of least resistance!

- Download Respberry Pi Imager from the raspberry pi page https://www.raspberrypi.org/downloads/raspbian/
- Press "Operating system" then select  "Raspberry Pi OS (Other)" > "Raspberry Pi OS Lite (32 bit)"
- Choose your storage
- Click the advanced cog icon, then fill out the info to enable headless boot
  - You could enter "octoprice" as the hostname
  - Enable SSH, and enter your public key or a password
  - Set a username and password
  - Configure Wireless LAN
  - Set your locale
  - Save
- Press write

Once imaged, put the SD card in your Pi and wait a while for it to boot (it can take 5-10 minutes). It should connect to your wifi, then you can ssh to it using `ssh <username>@<hostname>.local` replacing the username and hostname for those entered when imaging

Once you have an ssh terminal, you can get started with setting up our project

# Installing

- Install the libraries for inky phat using the [one line script from pimoroni](https://learn.pimoroni.com/tutorial/sandyj/getting-started-with-inky-phat)

  ```
  curl https://get.pimoroni.com/inky | bash
  ```

- Install git:

  ```
  sudo apt install git
  ```

- Clone PumpPrices

  ```
  git clone https://github.com/TwinUsers/PumpPrices.git
  cd PumpPrices
  ```

- Install requirements

  ```
  pip install -r requirements.txt
  ```
  ```
  python3 petrol.py
  ```

You should see your display update with the current price!
