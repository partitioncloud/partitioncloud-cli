#!/usr/bin/python3
import os

import requests
from bs4 import BeautifulSoup


class Config():
    def __init__(self):
        self.hostname = "https://partitioncloud.com"
        self.username = "username"
        self.password = "password"
        self.albums = [
            "f4ab565d-4fa7-43a0-8597-6cf1310af95c",
            "7fc34b40-445f-4678-91cb-f5be6932f6e8"
        ]
        self.storage_path = "/home/my-user/Documents/partitioncloud-files"

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
        if str(r) != "<Response [200]>":
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
    os.makedirs(config.storage_path, exist_ok=True)
    session = Session(config.hostname)
    session.login(config.username, config.password)
    albums = session.get_albums()
    albums.extend([Album(i, None, config.hostname) for i in config.albums])
    for album in albums:
        album.load_partitions(session.req_session)
        album.update(config.storage_path, session.req_session)





config = Config()
update_all(config)
