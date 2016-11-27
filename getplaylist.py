#!/usr/local/bin/python
# shows a user's playlists (need to be authenticated via oauth)

import eyed3
import pydub
import sys
import spotipy
import spotipy.util as util

def show_tracks(tracks):
    for i, item in enumerate(tracks['items']):
        track = item['track']
        duration_ms = track['duration_ms']
        duration_seconds = duration_ms / 1000.
        minutes, seconds = divmod(duration_seconds, 60)
        #print "* %d %s %s %d:%d" % (i, track['artists'][0]['name'], track['name'], minutes, seconds)

def writeTags(filePath, artist, title, album, genre, imagePath):
    audioFile = eyed3.load(filePath)
    if audioFile.tag is None:
        audioFile.initTag()
        audioFile.tag.save()
    audioFile.tag.artist = artist
    audioFile.tag.title = title
    audioFile.tag.album = album
    audioFile.tag.genre = genre

    image = open(imagePath,"rb").read()
    audioFile.tag.images.set(3, image, "image/png", u"cover")

    audioFile.tag.save()


if __name__ == '__main__':
    if len(sys.argv) > 1:
        username = sys.argv[1]
        wav_filepath = sys.argv[2]
    else:
        #print "Whoops, need your username!"
        #print "usage: python user_playlists.py [username]"
        sys.exit()

    wav_file = pydub.AudioSegment.from_mp3(wav_filepath)
    first_10_seconds = wav_file[:10000]
    first_10_seconds.export("something.mp3", format="mp3")
    writeTags("something.mp3", u"artist", u"title", u"album", u"genre", "pic.png")

    # token = util.prompt_for_user_token(username)
    #
    #
    # if token:
    #     sp = spotipy.Spotify(auth=token)
    #     playlists = sp.user_playlists(username)
    #     for playlist in playlists['items']:
    #         if playlist['owner']['id'] == username:
    #             print playlist['name']
    #             results = sp.user_playlist(username, playlist['id'],fields="tracks,next")
    #             tracks = results['tracks']
    #             show_tracks(tracks)
    #             while tracks['next']:
    #                 tracks = sp.next(tracks)
    #                 show_tracks(tracks)
    # else:
    #     print "Can't get token for", username
