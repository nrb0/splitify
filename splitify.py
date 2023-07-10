#!/usr/bin/env python

from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import eyed3
import math
import os
import pydub
import sys
import spotipy
import spotipy.util as util
import subprocess
import urllib.request

#-------------------------------------------------------------------------------

@dataclass
class TrackDescriptor:
    number: int = 0
    title: str = ""
    artist: str = ""
    album: str = ""
    coverURL: str = ""
    filename: str = ""
    startTime: int = 0
    endTime: int = 0
    parentPath: Path = Path()

@dataclass
class AudioFile:
    segment: pydub.AudioSegment
    path: Path

#-------------------------------------------------------------------------------

def exportSlice(sourcePath, destinationPath, startInMs, endInMs):
    startTime = formatTime(startInMs)
    endTime = formatTime(endInMs)

    subprocess.call(["ffmpeg", "-hide_banner", "-v", "quiet", "-stats",
        "-copyts", "-ss", startTime, "-i", sourcePath, "-to", endTime,
        "-c", "copy", destinationPath])

#-------------------------------------------------------------------------------

def convertToMP3(sourcePath, destinationPath):
    subprocess.call(["ffmpeg", "-hide_banner", "-v", "quiet", "-stats",
        "-i", sourcePath, "-ab", "320k", destinationPath])

#-------------------------------------------------------------------------------

def ask_question(message, possible_answers=[]):
    yes_no_question = len(possible_answers) == 0

    if yes_no_question:
        sys.stdout.write("%s [Y/n]? " % message)
    else:
        print("%s : " % message)
        answer_index = 1
        for answer in possible_answers:
            print("%d. %s" % (answer_index, str(answer)))
            answer_index += 1

    user_input = input()

    if yes_no_question:
        lower_input = user_input.lower()
        if lower_input == "y" or lower_input == "yes" or lower_input == "":
            return True
        elif lower_input == "n" or lower_input == "no":
            return False
    else:
        try:
            choice = int(user_input)
            if choice > 0 and choice <= len(possible_answers):
                return choice - 1
        except ValueError:
            print("Something")
    print("Invalid choice")
    return ask_question(message, possible_answers)

#-------------------------------------------------------------------------------

def askIntInput(message):
    sys.stdout.write("%s : " % message)
    user_input = input()
    if user_input == "":
        return 0
    try:
        value = int(user_input)
        return value
    except ValueError:
        print("Invalid input")
        return askIntInput(message)
    print("Invalid choice")
    return askIntInput(message)

#-------------------------------------------------------------------------------

def parseSeconds(inputString):
    seconds = 0
    milliseconds = 0
    parts = inputString.split(".")

    if len(parts) == 2:
        seconds = int(parts[0])
        milliseconds = int(parts[1])
    elif len(parts) == 1:
        seconds = int(parts[0])
    else:
        raise ValueError("")

    return seconds, milliseconds

#-------------------------------------------------------------------------------

def parseTimestamp(inputString):
    hours = 0
    minutes = 0
    seconds = 0
    milliseconds = 0

    parts = inputString.split(":")
    if len(parts) == 3:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds, milliseconds = parseSeconds(parts[2])
    elif len(parts) == 2:
        minutes = int(parts[0])
        seconds, milliseconds = parseSeconds(parts[1])
    elif len(parts) == 1:
        seconds, milliseconds = parseSeconds(parts[0])
    else:
        raise ValueError("")

    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + milliseconds

#-------------------------------------------------------------------------------

def askTimestampInput(message):
    print("{} : ".format(message))
    user_input = input()
    if user_input == "":
        return 0
    try:
        value = parseTimestamp(user_input)
        return value
    except ValueError:
        print("Invalid input")
        return askTimestampInput(message)
    print("Invalid choice")
    return askTimestampInput(message, possible_answers)

#-------------------------------------------------------------------------------

def sanitizeString(name):
    remove_punctuation_map = dict((ord(char), None) for char in '\/*?:"<>|')
    return name.translate(remove_punctuation_map)

#-------------------------------------------------------------------------------

def formatTime(durationInMs, with_ms=False):
    seconds, milliseconds = divmod(durationInMs, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)

    return "{:02d}:{:02d}:{:02d}.{:03d}".format(hours, minutes,
                                                seconds, milliseconds)

#-------------------------------------------------------------------------------

def getNearestSilence(audioSegment, position, within_seconds=20):
    analysisWindow = 100
    sliceSize = 1000

    for iteration in range(0, within_seconds):
        for forward in [True, False]:
            current_pos = position + iteration * (sliceSize if forward else sliceSize * -1)
            current_last_pos = current_pos
            if forward and current_pos + sliceSize < len(audioSegment):
                current_last_pos = current_pos + sliceSize
            elif forward and current_pos + sliceSize >= len(audioSegment):
                current_last_pos = len(audioSegment) - 1
            elif not forward and current_pos - sliceSize >= 0:
                current_last_pos = current_pos - sliceSize
            elif not forward and current_pos - sliceSize < 0:
                current_last_pos = 0
            for index in range(current_pos, current_last_pos):
                window_slice = audioSegment[index:index + analysisWindow]
                if window_slice.rms == 0:
                    return True, index
    print("ERROR: No silence were found")
    return False, position

#-------------------------------------------------------------------------------

def getFormattedArtists(artists):
    formattedTrackArtist = ""
    numberOfArtists = len(artists)

    for index, currentArtist in enumerate(artists):
        formattedTrackArtist = currentArtist['name']
        isLastArtists = index == numberOfArtists - 1

        if (numberOfArtists > 1) and not isLastArtists:
            formattedTrackArtist += ", "

    return formattedTrackArtist

#-------------------------------------------------------------------------------

def createTrackDescriptors(tracks, audioFile):
    descriptors = []

    sourceParentPath = audioFile.path.parent.absolute()
    sourceExtension = audioFile.path.suffix
    totalAudioLength = len(audioFile.segment)
    print("Audio file duration is {}".format(formatTime(totalAudioLength)))

    currentStartTime = 0

    for index, item in enumerate(tracks['items']):
        if currentStartTime >= totalAudioLength:
            print("End of file reached, aborting!")
            return descriptors

        track = item['track']
        descriptor = TrackDescriptor()

        # Store basic metadata
        descriptor.artist = getFormattedArtists(track['artists'])
        descriptor.title = track['name']
        descriptor.number = track['track_number']
        descriptor.album = track['album']['name']
        descriptor.coverURL = track['album']['images'][0]['url']
        descriptor.filename = "{:02d} {}".format(descriptor.number,
                                                 sanitizeString(descriptor.title))
        descriptor.parentPath = sourceParentPath
        
        descriptor.startTime = currentStartTime
        duration = track['duration_ms']
        descriptor.endTime = descriptor.startTime + duration

        # Analysis phase to find the end of the track based on silence
        print("* ANALYZING {} - {}...".format(descriptor.artist, descriptor.title))
        hasFoundSilence, descriptor.endTime = getNearestSilence(audioFile.segment,
                                                                descriptor.endTime)

        if hasFoundSilence:
            durationDelta = descriptor.endTime - descriptor.startTime - duration
            formattedDurationDelta = "{}{}".format("" if durationDelta >= 0 else "-",
                                                   formatTime(abs(durationDelta)))
            print("** Difference with original duration : {}".format(formattedDurationDelta))
        else:
            print("ERROR: Falling back to manual mode")
            print("** Original track duration : {}".format(formatTime(duration)))

        # export and compute the next starting point
        if not hasFoundSilence:
            descriptor = editTrackTimesInteractive(audioFile, descriptor)

        currentStartTime = descriptor.endTime + 1
        descriptors.append(descriptor)

    return descriptors

#-------------------------------------------------------------------------------

def writeTags(filePath, descriptor):
    print("* TAGGING: {}".format(descriptor.title))
    audioFile = eyed3.load(filePath)

    if audioFile.tag is None:
        audioFile.initTag()

    audioFile.tag.artist = descriptor.artist
    audioFile.tag.title = descriptor.title
    audioFile.tag.album = descriptor.album
    audioFile.tag.track_num = descriptor.number

    if descriptor.coverURL != "":
        urllib.request.urlretrieve(descriptor.coverURL, "pic.jpeg")
        pic = open("pic.jpeg", "rb").read()
        audioFile.tag.images.set(3, pic, "image/jpeg", u"cover")
        os.remove("pic.jpeg")

    audioFile.tag.save()

#-------------------------------------------------------------------------------

def convertAndTag(sourcePath, descriptors):
    sourceExtension = sourcePath.suffix

    for descriptor in descriptors:
        print("* CONVERTING {} - {}...".format(descriptor.artist, descriptor.title))
        tempPath = os.path.join(descriptor.parentPath,
            "{}{}".format(descriptor.filename, sourceExtension))

        exportSlice(sourcePath, tempPath, descriptor.startTime, descriptor.endTime)

        convertedFilePath = os.path.join(descriptor.parentPath,
            "{}{}".format(descriptor.filename, ".mp3"))

        convertToMP3(tempPath, convertedFilePath)
        os.remove(tempPath)

        writeTags(convertedFilePath, descriptor)

#-------------------------------------------------------------------------------

def getTracksFromSpotifyPlaylist(spotifyAccess, username, playlistName):
    playlists = spotifyAccess.user_playlists(username)

    for playlist in playlists['items']:
        nameMatch = playlist['owner']['id'] == username
        playlistMatch = playlist['name'] == playlistName
        if (nameMatch and playlistMatch):
            results =  spotifyAccess.user_playlist(username,
                playlist['id'],fields="tracks, next")
            return results['tracks']

    return None

#-------------------------------------------------------------------------------

def editTrackTimesInteractive(audioFile, descriptor):
    sourceExtension = audioFile.path.suffix
    destinationPath = os.path.join(descriptor.parentPath,
        "{}{}".format(descriptor.filename, sourceExtension))

    totalAudioLength = len(audioFile.segment)
    isTrackEndBeyondEndOfFile = descriptor.endTime >= totalAudioLength

    startTime = descriptor.startTime
    endTime = totalAudioLength - 1 if isTrackEndBeyondEndOfFile else descriptor.endTime

    print("* EXPORTING {} - {}...".format(descriptor.artist, descriptor.title))
    print("** from {} to {} ...".format(formatTime(startTime),
                                        formatTime(endTime)))
    if isTrackEndBeyondEndOfFile:
        print("** WARNING: End of file reached, file might be incomplete")

    exportSlice(sourcePath, destinationPath, startTime, endTime)
    isExportOk = ask_question("Is the export correct")

    if (not isExportOk):
        shouldChangeStart = ask_question("Change start time?")
        if shouldChangeStart:
            choice = ask_question("How to edit?",
                                  ["Provide start timestamp",
                                   "Provide offset for the current start time"])
            if choice == 0:
                startTime = askTimestampInput("Enter start timestamp [HH:MM:SS.MS]")
            else:
                startTime += askIntInput("Enter start offset (in ms)")

        shouldChangeEnd = ask_question("Change end time?")
        if shouldChangeEnd:
            choice = ask_question("How to edit?",
                                  ["Provide end timestamp",
                                   "Provide offset for the current end time"])
            if choice == 0:
                endTime = askTimestampInput("Enter end timestamp [HH:MM:SS.MS]")
            else:
                endTime += askIntInput("Enter end offset (in ms)")

    os.remove(destinationPath)
    descriptor.startTime = 0 if startTime < 0 else startTime
    descriptor.endTime = totalAudioLength if endTime >= totalAudioLength else endTime

    if isExportOk:
        return descriptor
    else:
        return editTrackTimesInteractive(audioFile, descriptor)

#-------------------------------------------------------------------------------

def editMenuOverview(audioFile, descriptors):
    for index, descriptor in enumerate(descriptors):
        print("{}. {} - {}".format(index + 1, descriptor.artist, descriptor.title))

    shouldEdit = ask_question("Edit any track?")

    while shouldEdit:
        index = askIntInput("Which track?")

        if index > 0 and index <= len(descriptors):
            newDescriptor = editTrackTimesInteractive(audioFile, descriptors[index - 1])
            descriptor[index - 1] = newDescriptor
        else:
            print("Invalid index!")

        shouldEdit = ask_question("Edit another track?")

    return descriptors

#-------------------------------------------------------------------------------

if __name__ == '__main__':
    if len(sys.argv) != 4:
        print("usage: splitify.py username spotifyPlaylistName path/to/ripped/wav")
        sys.exit()

    user = sys.argv[1]
    playlist = sys.argv[2]
    sourcePath = Path(sys.argv[3])

    if not sourcePath.exists() or not os.path.isfile(sourcePath):
        print("Invalid path to file")
        sys.exit()

    # Get playlist from spotify
    token = util.prompt_for_user_token(user)
    if not token:
        print("Can't get token for", user)
        exit()

    spotifyAccess = spotipy.Spotify(auth=token)
    tracks = getTracksFromSpotifyPlaylist(spotifyAccess, user, playlist)
    if tracks == None:
        print("Can't find playlist \"{}\" in user \"{}\"".format(playlist, user))
        exit()

    # Process audio file
    audioFile = AudioFile(pydub.AudioSegment.from_wav(sourcePath), sourcePath)
    descriptors = createTrackDescriptors(tracks, audioFile)

    # Edit results
    descriptors = editMenuOverview(audioFile, descriptors)

    # Convert results
    convertAndTag(sourcePath, descriptors)

    print("k thx bye")

#-------------------------------------------------------------------------------
