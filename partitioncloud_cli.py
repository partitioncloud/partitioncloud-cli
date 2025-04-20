#!/usr/bin/python3
import configparser
import argparse
import requests
import inspect
import fnmatch
import shutil
import json
import os

from pathlib import Path
from bs4 import BeautifulSoup


def file_safe_string(s):
    return "".join([c for c in s if c.isdigit() or c.isalpha() or c == " " or c == "-"]).strip()

NO_CONFIRM = False
def confirm(text, default=False):
    if NO_CONFIRM:
        return default
    try:
        return input(text+" [y/N] ").lower() == "y"
    except (KeyboardInterrupt, EOFError):
        exit(1)

def curry_function(func):
    """Curries a function by creating nested functions for each argument."""
    num_args = len(inspect.signature(func).parameters)

    def curried(*args):
        if len(args) >= num_args:
            return func(*args)
        else:
            return lambda *next_args: curried(*(args + next_args))

    return curried

def arborescent_file_loc(config, groupe, album, partition):
    """
    Returns the desired path of a partition
    - {groupe}/{album}/{partition name} if any group
    - {album}/{partition name} otherwise
    """
    if groupe is not None:
        return os.path.join(config["STORAGE"]["storage-path"], groupe.name, album.name, f"{partition}.pdf")
    return os.path.join(config["STORAGE"]["storage-path"], album.name, f"{partition}.pdf")

def flat_file_loc(config, groupe, album, partition):
    """
    Returns the desired path of a partition
    - case of a flat arborescence
    """
    return os.path.join(config["STORAGE"]["storage-path"], f"{partition}.pdf")


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


    def update(self, req_session, file_loc_fun):
        for partition in self.partitions:
            partition.update(self.host, req_session, file_loc_fun(self))


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


    def load_albums(self, req_session):
        r = req_session.get(f"{self.host}/groupe/{self.id}")
        soup = BeautifulSoup(r.content, "html.parser")
        albums_section = soup.find("section", {"id": "albums-grid"})
        self.albums = [Album(i["href"].split("/")[-1], i.text.strip(), self.host) for i in albums_section.find_all("a")]


    def load_partitions(self, req_session):
        if self.albums is None:
                self.load_albums(req_session)

        for album in self.albums:
            album.load_partitions(req_session)


    def update(self, req_session, file_loc_fun):
        if self.albums is None:
                self.load_albums(req_session)

        for album in self.albums:
            album.update(req_session, file_loc_fun(self))


    def __repr__(self):
        return self.name


class Partition():
    def __init__(self, id, author, name, album):
        self.album = album
        self.id = id
        self.name = name
        self.author = author


    def update(self, host, req_session, file_loc_fun):
        path = file_loc_fun(self)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            print(f"Downloading {self.album.name}/{self.name}")
            with req_session.get(f"{host}/partition/{self.id}", stream=True) as r:
                r.raise_for_status()
                with open(path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)

    def get_attachments(self, host, req_session):
        r = req_session.get(f"{host}/partition/{self.id}/attachments")
        soup = BeautifulSoup(r.content, "html.parser")
        attachments_soup = soup.find("div", {"id": "attachments"})
        if attachments_soup is None:
            return []
        
        attachments = []
        for att in attachments_soup.find_all("tr"):
            audio, name = att.find_all("td")
            link = list(audio.children)[0]["src"]
            attachments.append({
                "uuid": link.split("/")[-1].split(".")[0],
                "ext": link.split("/")[-1].split(".")[1],
                "title": name.text[2:].strip()
            })

        return attachments

    def post_attachment(self, filename, name, host, req_session):
        assert filename.split('.')[-1] in ["mp3", "mid", "midi"]
        data = {
            "name": name.strip()
        }
        files = {
            'file': open(filename,'rb')
        }
        return req_session.post(
            f"{host}/partition/{self.id}/add-attachment",
            data=data,
            files=files
        )

    def __repr__(self):
        if self.author != "":
            return f"{self.name} - {self.author}"
        return file_safe_string(self.name)



def update_all(config, file_loc_fun=None, flat=False):

    if file_loc_fun is None:
        file_loc_fun = arborescent_file_loc
        if flat:
            file_loc_fun = flat_file_loc
    file_loc_fun = curry_function(file_loc_fun)(config)

    os.makedirs(config["STORAGE"]["storage-path"], exist_ok=True)
    session = Session(config["SERVER"]["hostname"])

    if config["AUTH"].get("username", "") != "" and config["AUTH"]["username"] is not None:
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

    if "groupes" in config["AUTH"].keys():
        groupes.extend([Groupe(i, None, None, config["SERVER"]["hostname"]) for i in json.loads(config["AUTH"]["groupes"])])

    for album in albums:
        album.load_partitions(session.req_session)
        album.update(
            session.req_session,
            file_loc_fun(None)
        )

    for groupe in groupes:
        groupe.load_partitions(session.req_session)
        groupe.update(
            session.req_session,
            file_loc_fun
        )


def attach_files(config, uuid, files):
    def determine_name(file):
        if "ATTACHMENTS_ALIAS" not in config:
            return file, False
        
        for name in config["ATTACHMENTS_ALIAS"]:
            for pattern in json.loads(config["ATTACHMENTS_ALIAS"][name]):
                if fnmatch.fnmatch(file, pattern):
                    return name.capitalize(), True

        return file, False

    partition = Partition(uuid, None, None, None)
    files_map = []
    for file in files:
        name = ".".join(file.split("/")[-1].split(".")[:-1])
        modified = False
        if ':' in file:
            name = ":".join(file.split(":")[1:])
            file = file.split(":")[0]
        else:
            name, modified = determine_name(name)
        
        files_map.append((file, name, modified))

    print("\n".join(f"Uploading {file} as {name}" for file, name, _ in files_map))
    if not confirm("Confirm these names ?", default=True):
        exit(1)

    if config["AUTH"]["username"] == "" or config["AUTH"]["username"] is None:
        raise ValueError("Incomplete authentication data")

    session = Session(config["SERVER"]["hostname"])
    session.login(config["AUTH"]["username"], config["AUTH"]["password"])

    for file, name, _ in files_map:
        partition.post_attachment(file, name, config["SERVER"]["hostname"], session.req_session)



def __main__():
    def parse_args():
        parser = argparse.ArgumentParser(description="CLI for PartitionCloud")
        subparsers = parser.add_subparsers(dest="action", help="Available commands")
        parser.add_argument("-c", "--config", dest="config_file", action="store",
                            default=os.path.join(str(Path.home()), ".partitioncloud-config"),
                            help="Path to config file (containing credentials etc)")
        parser.add_argument("-y", "--yes", dest="no_confirm", action="store_true",
                            help="Skip confirmations")

        sync_parser = subparsers.add_parser("sync", help="Sync data from server specified in config")
        sync_parser.add_argument("--flat", dest="flat", action="store_true",
                            help="Do not create folders")

        attach_parser = subparsers.add_parser("attach", help="Add attachments to partition")
        attach_parser.add_argument("uuid", type=str, help="Partition uuid")
        attach_parser.add_argument("files", nargs="+", help="Files to attach (file:name if needed)")

        return parser.parse_args()

    args = parse_args()
    config = configparser.ConfigParser()

    global NO_CONFIRM
    NO_CONFIRM = args.no_confirm

    if not os.path.exists(args.config_file):
        shutil.copyfile(".partitioncloud-config.sample", args.config_file)
        print(f"No config file was found, copying default to {args.config_file}")
        print("Modify it for your needs and relaunch this script")
        exit(1)
    
    config.read(args.config_file)

    match args.action:
        case "sync":
            update_all(config, flat=args.flat)
        case "attach":
            attach_files(config, args.uuid, args.files)
        case None:
            print("You now need to specify an action. Specify `sync` to replicate previous behavior.")
            exit(1)



if __name__ == "__main__":
    __main__()
