#!/usr/local/bin/python
# shows a user's playlists (need to be authenticated via oauth)

import eyed3
import os
import pydub
import sys
import spotipy
import spotipy.util as util
import urllib

def removeIllegalCharacters(name):
    remove_punctuation_map = dict((ord(char), None) for char in '\/*?:"<>|')
    return name.translate(remove_punctuation_map)

def getNextSilentPosition(rippedFile, position, windowSize=300, threshold=-16):
    lastAvailablePosition = len(rippedFile) - windowSize
    for index in range(position, lastAvailablePosition):
        audioSlice = rippedFile[index:index + windowSize]
        currentRMS = audioSlice.rms
        if currentRMS == 0:
            return index + windowSize

    return position

def processTracks(tracks, rippedFile, totalLength, currentStartPosition, playlistName):
    for index, item in enumerate(tracks['items']):
        track = item['track']
        artist = track['artists'][0]['name']
        title = track['name']
        pictureURL = track['album']['images'][0]['url']
        trackPath = " %02d %s - %s.mp3" % (index+1, removeIllegalCharacters(artist), removeIllegalCharacters(title))
        picPath = "pic%d.jpeg" % (index)
        print "Preparing : %s - %s" % (artist, title)
        endPosition = getNextSilentPosition(rippedFile, currentStartPosition + track['duration_ms'])
        if endPosition > totalLength:
            endPosition = totalLength
            trackPath = "(INCOMPLETE)" + trackPath

        startM, startS = divmod(currentStartPosition/1000., 60)
        endM, endS = divmod(endPosition/1000., 60)

        if currentStartPosition < totalLength:
            print "(%d:%d->%d:%d) exporting ..." % (startM, startS, endM, endS)
            currentAudio = rippedFile[currentStartPosition:endPosition]
            currentAudio.export(trackPath, format="mp3")
            currentStartPosition = endPosition + 1
            urllib.urlretrieve(pictureURL, picPath)
            writeTags(trackPath, unicode(artist), unicode(title), unicode(playlistName), picPath)
            os.remove(picPath)

def writeTags(filePath, artist, title, album, imagePath):
    audioFile = eyed3.load(filePath)
    if audioFile.tag is None:
        audioFile.initTag()
        audioFile.tag.save()
    audioFile.tag.artist = artist
    audioFile.tag.title = title
    audioFile.tag.album = album

    image = open(imagePath,"rb").read()
    audioFile.tag.images.set(3, image, "image/jpeg", u"cover")

    audioFile.tag.save()


if __name__ == '__main__':
    if len(sys.argv) > 1:
        userName = sys.argv[1]
        playlistName = sys.argv[2]
        rippedFilePath = sys.argv[3]
    else:
        #print "Whoops, need your username!"
        #print "usage: python user_playlists.py [username]"
        sys.exit()

    # Start by getting the ripped file and preparing some data for iterating
    rippedFile = pydub.AudioSegment.from_mp3(rippedFilePath)
    totalLength = len(rippedFile)
    print "Audio file duration is %d:%d" % divmod(totalLength / 1000., 60)
    currentStartPosition = 0

    # Init spotify data, exit if it fails
    token = util.prompt_for_user_token(userName)
    if not token:
        print "Can't get token for", userName
        exit()

    sp = spotipy.Spotify(auth=token)
    playlists = sp.user_playlists(userName)
    for playlist in playlists['items']:
        if (playlist['owner']['id'] == userName and
            playlist['name'] == playlistName):
            results = sp.user_playlist(userName, playlist['id'],fields="tracks, next")
            tracks = results['tracks']
            processTracks(tracks, rippedFile, totalLength, currentStartPosition, playlistName)
            while tracks['next']:
                tracks = sp.next(tracks)
                processTracks(tracks, rippedFile, totalLength, currentStartPosition, playlistName)
