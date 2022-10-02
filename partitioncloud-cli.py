#!/usr/bin/python3
import configparser
import json
import os
import shutil
from pathlib import Path

import requests
from bs4 import BeautifulSoup


class Session():
    def __init__(self, hostname):
        self.req_session = requests.Session()
        self.host = hostname
        self.username = None
        self.password = None

    def login(self, username, password):
        data = {
            "username": username,
            "password": password
        }
        r = self.req_session.post(f"{self.host}/auth/login", data)
        if "<title>Se connecter - PartitionCloud</title>" in r.text:
            raise BaseException("Invalid username/ password")

    def get_albums(self):
        r = self.req_session.get(f"{self.host}/albums")
        soup = BeautifulSoup(r.content, "html.parser")
        a = soup.find("section", {"id": "albums"}).find_all("a")
        return [Album(i["href"], i.text.strip(), self.host) for i in a]


class Album():
    def __init__(self, id, name, host):
        self.id = id
        self.name = name
        self.host = host
        self.partitions = []

    def load_partitions(self, req_session):
        r = req_session.get(f"{self.host}/albums/{self.id}")
        soup = BeautifulSoup(r.content, "html.parser")
        if self.name is None:
            self.name = soup.find("header").find("h1").text.strip()

        a = soup.find("div", {"id": "partitions-grid"}).find_all("a")

        for partition_div in a:
            id = partition_div["href"].split("/")[-1]
            author = partition_div.find("div", {"class": "partition-author"}).text.strip()
            name = partition_div.find("div", {"class": "partition-name"}).text.strip()
            self.partitions.append(Partition(id, author, name, self))

    def update(self, storage_path, req_session):
        os.makedirs(os.path.join(storage_path, self.name), exist_ok=True)
        for partition in self.partitions:
            partition.update(self.host, storage_path, req_session)

    def __repr__(self):
        return self.name


class Partition():
    def __init__(self, id, author, name, album):
        self.album = album
        self.id = id
        self.name = name
        self.author = author

    def update(self, host, storage_path, req_session):
        path = os.path.join(storage_path, self.album.name, f"{self}.pdf")
        if not os.path.exists(path):
            print(f"Downloading {self.album.name}/{self.name}")
            with req_session.get(f"{host}/albums/{self.album.id}/{self.id}", stream=True) as r:
                r.raise_for_status()
                with open(path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)

    def __repr__(self):
        if self.author != "":
            return f"{self.name} - {self.author}"
        return self.name



def update_all(config):
    os.makedirs(config["STORAGE"]["storage-path"], exist_ok=True)
    session = Session(config["SERVER"]["hostname"])

    if config["AUTH"]["username"] != "" and config["AUTH"]["username"] is not None:
        session.login(config["AUTH"]["username"], config["AUTH"]["password"])
        albums = session.get_albums()
    else:
        albums = []

    albums.extend([Album(i, None, config["SERVER"]["hostname"]) for i in json.loads(config["AUTH"]["albums"])])

    for album in albums:
        album.load_partitions(session.req_session)
        album.update(config["STORAGE"]["storage-path"], session.req_session)



def __main__():
    home = str(Path.home())
    config = configparser.ConfigParser()
    config_file = os.path.join(home, ".partitioncloud-config")

    if not os.path.exists(config_file):
        shutil.copyfile(".partitioncloud-config.sample", config_file)
        print(f"No config file was found, copying default to {config_file}")
        print("Modify it for your needs and relaunch this script")
        exit(1)
    
    config.read(config_file)
    update_all(config)


if __name__ == "__main__":
    __main__()
