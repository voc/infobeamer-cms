# 36C3 CMS

![36c3](36c3-example.jpg)

# About

This is a quickly hacked together content management system
running at the [36C3 event](https://events.ccc.de/congress/2019/) in
late 2019.

It allows login to users with github accounts and they can upload
images/videos. Upon moderation approval it will sync them into a
playlist in a [scheduled player](https://info-beamer.com/pkg/4765) based setup.

It uses the new [adhoc access feature](https://info-beamer.com/doc/api#createadhocaccess)
and users will directly upload their assets to info-beamer.com.

Consider this example code and this repository should be treated
as a code dump instead of a finished product. The code might help
you understand how to use the info-beamer API though.

# Installation

Should work somewhat like this on Ubuntu or Debian:

```
git clone this_repo /opt/infobeamer-cms && cd /opt/infobeamer-cms
python3 -m virtualenv env
. env/bin/activate
pip3 install -r requirements.txt
```

As for running in "production":

```
apt install nginx-full
cp infobeamer-cms-nginx.conf /etc/nginx/sites-enabled/
# put required certs into referenced directory
systemctl restart nginx

# adapt those settings
cp settings.example.toml settings.toml

# start via systemd
cp infobeamer-cms.service /etc/systemd/system/
cp infobeamer-cms-runperiodic.service /etc/systemd/system/
cp infobeamer-cms-runperiodic.timer /etc/systemd/system/
```
