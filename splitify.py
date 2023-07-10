#!/opt/homebrew/bin/python3

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

tracksToExport = []

#-------------------------------------------------------------------------------

def exportSlice(sourcePath, destinationPath, startInMs, endInMs):
    startTime = format_ms_time(startInMs)
    endTime = format_ms_time(endInMs)

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
                return possible_answers[choice - 1]
        except ValueError:
            print("Something")
    print("Invalid choice")
    return ask_question(message, possible_answers)

#-------------------------------------------------------------------------------

def ask_int_input(message):
    sys.stdout.write("%s : " % message)
    user_input = input()
    if user_input == "":
        return 0
    try:
        value = int(user_input)
        return value
    except ValueError:
        print("Invalid input")
        return ask_int_input(message)
    print("Invalid choice")
    return ask_question(message, possible_answers)

#-------------------------------------------------------------------------------

def remove_illegal_characters(name):
    remove_punctuation_map = dict((ord(char), None) for char in '\/*?:"<>|')
    return name.translate(remove_punctuation_map)

#-------------------------------------------------------------------------------

def format_ms_time(durationInMs, with_ms=False):
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

def export_slice(audioSegment, sourcePath, descriptor, interactive):
    sourceExtension = sourcePath.suffix
    destinationPath = os.path.join(descriptor.parentPath,
        "{}{}".format(descriptor.filename, sourceExtension))

    totalAudioLength = len(audioSegment)
    isEndOfFile = descriptor.endTime >= totalAudioLength

    startTime = descriptor.startTime
    currentEndTime = totalAudioLength - 1 if isEndOfFile else descriptor.endTime

    print("* EXPORTING...")
    print("** from {} to {} ...".format(format_ms_time(startTime),
                                        format_ms_time(currentEndTime)))
    if isEndOfFile:
        print("** WARNING: End of file reached, file might be incomplete")

    exportSlice(sourcePath, destinationPath, startTime, currentEndTime)

    if (isEndOfFile or not interactive or interactive and ask_question("Is the export correct")):
        os.remove(destinationPath)

        descriptor.endTime = currentEndTime
        return descriptor
    else:
        os.remove(destinationPath)

        startOffset = ask_int_input("Start offset (in ms)")
        endOffset = ask_int_input("End offset (in ms)")
        descriptor.startTime += startOffset
        descriptor.endTime += endOffset

        return export_slice(audioSegment, sourcePath, descriptor, interactive)

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

def createAndAppendDescriptor(tracks, audioSegment, sourcePath, currentStartTime):
    sourceParentPath = sourcePath.parent.absolute()
    sourceExtension = sourcePath.suffix

    for index, item in enumerate(tracks['items']):
        # first check if we are not trying to export out of range
        if currentStartTime == len(audioSegment):
            print("EOF reached, aborting!")
            return

        # store track metadata
        track = item['track']

        descriptor = TrackDescriptor()
        descriptor.artist = getFormattedArtists(track['artists'])
        descriptor.title = track['name']
        descriptor.number = track['track_number']
        descriptor.album = track['album']['name']
        descriptor.coverURL = track['album']['images'][0]['url']
        descriptor.filename = "{:02d} {}".format(descriptor.number, 
                                                 remove_illegal_characters(descriptor.title))
        descriptor.parentPath = sourceParentPath
        descriptor.startTime = currentStartTime

        durationInMs = track['duration_ms']

        print("----- %s - %s -----" % (descriptor.artist, descriptor.title))

        # Analysis phase to find the end of the track based on silence
        print("* ANALYZING...")
        hasFoundSilence, concreteEnd = getNearestSilence(audioSegment,
                                            currentStartTime + durationInMs)
        descriptor.endTime = concreteEnd

        if not hasFoundSilence:
            print("ERROR: Falling back to manual mode")
            print("** Original track duration : {}".format(format_ms_time(durationInMs)))
        else:
            durationDelta = concreteEnd - descriptor.startTime - durationInMs
            formattedDurationDelta = "{}{}".format("" if durationDelta >= 0 else "-",
                                                   format_ms_time(abs(durationDelta)))
            print("** Difference with original duration : {}".format(formattedDurationDelta))

        # export and compute the next starting point
        descriptor = export_slice(ripped_file, sourcePath, descriptor, not hasFoundSilence)
        currentStartTime = descriptor.endTime + 1

        tracksToExport.append(descriptor)

    return currentStartTime

#-------------------------------------------------------------------------------

def appendToExportTask(descriptor):
    print("Hello")

#-------------------------------------------------------------------------------

def write_tags(filePath, descriptor):
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

if __name__ == '__main__':
    if len(sys.argv) > 1:
        username = sys.argv[1]
        playlist_name = sys.argv[2]
        ripped_filepath = sys.argv[3]
    else:
        print("usage: user_playlists.py username spotifyPlaylistName path/to/ripped/wav")
        sys.exit()

    # Start by getting the ripped file and preparing some data for iterating
    ripped_file = pydub.AudioSegment.from_wav(ripped_filepath)
    sourcePath = Path(ripped_filepath)
    print("Audio file duration is %d:%d" % divmod(len(ripped_file) / 1000., 60))
    curr_start_pos = 0

    # Init spotify data, exit if it fails
    token = util.prompt_for_user_token(username)
    if not token:
        print("Can't get token for", username)
        exit()
    sp = spotipy.Spotify(auth=token)
    playlists = sp.user_playlists(username)
    for playlist in playlists['items']:
        if (playlist['owner']['id'] == username and
           playlist['name'] == playlist_name):
            results = sp.user_playlist(username,
                                       playlist['id'],fields="tracks, next")
            tracks = results['tracks']
            curr_start_pos = createAndAppendDescriptor(tracks, ripped_file,
                sourcePath, curr_start_pos)
            while tracks['next']:
                tracks = sp.next(tracks)
                curr_start_pos = createAndAppendDescriptor(tracks, ripped_file,
                    sourcePath, curr_start_pos)

    for descriptor in tracksToExport:
        sourceExtension = sourcePath.suffix
        tempPath = os.path.join(descriptor.parentPath,
            "{}{}".format(descriptor.filename, sourceExtension))
        print("sourcePath: {}\ntempPath: {}".format(sourcePath, tempPath))
        exportSlice(sourcePath, tempPath, descriptor.startTime, descriptor.endTime)

        convertedFilePath = os.path.join(descriptor.parentPath,
            "{}{}".format(descriptor.filename, ".mp3"))
        convertToMP3(tempPath, convertedFilePath)
        os.remove(tempPath)

        write_tags(convertedFilePath, descriptor)

#-------------------------------------------------------------------------------
