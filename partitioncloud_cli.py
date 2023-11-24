#!/usr/bin/python3
import configparser
import argparse
import json
import os
import shutil
from pathlib import Path

import requests
from bs4 import BeautifulSoup


def file_safe_string(s):
    return "".join([c for c in s if c.isdigit() or c.isalpha() or c == " " or c == "-"]).strip()



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


    def get_albums(self, content=None):
        if content is None:
            r = self.req_session.get(f"{self.host}/albums")
            content = r.content
        soup = BeautifulSoup(content, "html.parser")
        a = soup.find("section", {"id": "albums"}).find_all("a")
        return [Album(i["href"].split("/")[-1], i.text.strip(), self.host) for i in a]


    def get_groupes(self, content=None):
        if content is None:
            r = self.req_session.get(f"{self.host}/albums")
            content = r.content
        soup = BeautifulSoup(content, "html.parser")
        section = soup.find("section", {"id": "groupes"})

        groupes = []
        for groupe in section.find_all("div", {"class": "groupe-cover"}):
            header = groupe.find("summary").find("a")
            name = header.text.strip()
            uuid = header["href"].split("/")[-1]

            albums_dom = groupe.find("div", {"class": "groupe-albums-cover"})
            albums = [Album(i["href"].split("/")[-1], i.text.strip(), self.host) for i in albums_dom.find_all("a")]

            groupes.append(Groupe(uuid, name, albums, self.host))

        return groupes
        

    def upload(self, album_id: str, filename: str, name: str, author="", lyrics="") -> requests.models.Response:
        """Uploads a score with the specified parameters to the album specified by album_id"""
        data = {
            "name": name,
            "author": author,
            "body": lyrics
        }
        files = {
            'file': open(filename,'rb')
        }
        return self.req_session.post(
            f"{self.host}/albums/{album_id}/add-partition",
            data=data,
            files=files
        )


    def create_album(self, name: str):
        """Creates an album and returns the associated object"""
        req = self.req_session.post(
            f"{self.host}/albums/create-album",
            data={"name": name}
        )
        return Album(req.url.split("/")[-1], name, self.host)



class Album():
    def __init__(self, id, name, host):
        self.id = id
        self.host = host
        self.partitions = []
        if name is not None:
            # Will else be loaded in `self.load_partitions()`
            self.name = file_safe_string(name)
        else:
            self.name = None


    def load_partitions(self, req_session):
        r = req_session.get(f"{self.host}/albums/{self.id}")
        soup = BeautifulSoup(r.content, "html.parser")
        if self.name is None:
            self.name = file_safe_string(soup.find("h2", {"id": "album-title"}).text.strip())

        partition_divs = soup.find("section", {"id": "partitions-grid"}).find_all("div", {"class": "partition"})
        for partition_div in partition_divs:
            id = "-".join(partition_div["id"].split("-")[1:])
            name = partition_div.find("div", {"class": "partition-name"}).text.strip()
            author = partition_div.find("div", {"class": "partition-author"}).text.strip()
            self.partitions.append(Partition(id, author, name, self))


    def update(self, storage_path, req_session):
        os.makedirs(os.path.join(storage_path, self.name), exist_ok=True)
        for partition in self.partitions:
            partition.update(self.host, storage_path, req_session)


    def __repr__(self):
        return self.name


class Groupe():
    def __init__(self, id, name, albums, host):
        self.id = id
        self.host = host
        self.albums = albums
        if name is not None:
            # Will else be loaded in `self.load_partitions()`
            self.name = file_safe_string(name)
        else:
            self.name = None


    def load_partitions(self, req_session):
        for album in self.albums:
            album.load_partitions(req_session)


    def update(self, storage_path, req_session):
        dest = os.path.join(storage_path, self.name)
        os.makedirs(dest, exist_ok=True)
        for album in self.albums:
            album.update(dest, req_session)


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
            with req_session.get(f"{host}/partition/{self.id}", stream=True) as r:
                r.raise_for_status()
                with open(path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)


    def __repr__(self):
        if self.author != "":
            return f"{self.name} - {self.author}"
        return file_safe_string(self.name)



def update_all(config):
    os.makedirs(config["STORAGE"]["storage-path"], exist_ok=True)
    session = Session(config["SERVER"]["hostname"])

    if config["AUTH"]["username"] != "" and config["AUTH"]["username"] is not None:
        session.login(config["AUTH"]["username"], config["AUTH"]["password"])

        r = session.req_session.get(f"{session.host}/albums")
        content = r.content

        albums = session.get_albums(content=content)
        groupes = session.get_groupes(content=content)
    else:
        albums = []
        groupes = []

    if "albums" in config["AUTH"].keys():
        albums.extend([Album(i, None, config["SERVER"]["hostname"]) for i in json.loads(config["AUTH"]["albums"])])

    for album in albums:
        album.load_partitions(session.req_session)
        album.update(config["STORAGE"]["storage-path"], session.req_session)

    for groupe in groupes:
        groupe.load_partitions(session.req_session)
        groupe.update(config["STORAGE"]["storage-path"], session.req_session)



def __main__():
    parser = argparse.ArgumentParser(description="CLI for PartitionCloud")
    parser.add_argument("-c", "--config", dest="config_file", action="store",
                        default=os.path.join(str(Path.home()), ".partitioncloud-config"),
                        help="Path to config file (containing credentials etc)")

    args = parser.parse_args()

    config = configparser.ConfigParser()

    if not os.path.exists(args.config_file):
        shutil.copyfile(".partitioncloud-config.sample", args.config_file)
        print(f"No config file was found, copying default to {args.config_file}")
        print("Modify it for your needs and relaunch this script")
        exit(1)
    
    config.read(args.config_file)
    update_all(config)



if __name__ == "__main__":
    __main__()
