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
    number: int
    title: str
    artist: str
    album: str
    coverURL: str
    filename: str
    duration: int

#-------------------------------------------------------------------------------

def exportSlice(sourcePath, destinationFilename, startInMs, endInMs):
    sourceParentPath = sourcePath.parent.absolute()
    sourceExtension = sourcePath.suffix
    sourceFileName = sourcePath.stem

    startTime = format_ms_time(startInMs)
    endTime = format_ms_time(endInMs)

    destinationFormat = os.path.join(sourceParentPath,
        "{}{}".format(destinationFilename, ".mp3"))

    subprocess.call(["ffmpeg", "-hide_banner", "-v", "quiet", "-stats",
        "-copyts", "-ss", startTime, "-i", sourcePath, "-to", endTime,
        "-ab", "320k", destinationFormat])

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

def get_nearest_silence(audio, position, within_seconds=20):
    analysis_window = 100
    slice_size = 1000
    for iteration in range(0, within_seconds):
        for forward in [True, False]:
            current_pos = position + iteration * (slice_size if forward else slice_size * -1)
            current_last_pos = current_pos
            if forward and current_pos + slice_size < len(audio):
                current_last_pos = current_pos + slice_size
            elif forward and current_pos + slice_size >= len(audio):
                current_last_pos = len(audio) - 1
            elif not forward and current_pos - slice_size >= 0:
                current_last_pos = current_pos - slice_size
            elif not forward and current_pos - slice_size < 0:
                current_last_pos = 0
            for index in range(current_pos, current_last_pos):
                window_slice = audio[index:index + analysis_window]
                if window_slice.rms == 0:
                    return True, index
    print("ERROR: No silence were found")
    return False, position

#-------------------------------------------------------------------------------

def export_slice(ripped_file, sourceFilePath, start_pos, end_pos, file_name, interactive):
    full_path = file_name
    local_end_position = end_pos
    end_of_file = local_end_position >= len(ripped_file)

    if end_of_file:
        local_end_position = len(ripped_file) - 1
        full_path = "(INCOMPLETE) " + file_name

    print("* EXPORTING...")
    print("** from %s to %s ..." % (format_ms_time(start_pos),
                                    format_ms_time(local_end_position)))
    audio_slice = ripped_file[start_pos:local_end_position]
    # audio_slice.export(full_path, format="mp3")
    exportSlice(sourceFilePath, file_name, start_pos, local_end_position)

    if (end_of_file or
       not interactive or
       interactive and ask_question("Is the export correct")):
        return local_end_position + 1
    else:
        os.remove(full_path)
        start_offset = ask_int_input("Start offset (in ms)")
        end_offset = ask_int_input("End offset (in ms)")
        return export_slice(ripped_file, start_pos + start_offset,
            end_pos + end_offset, full_path, interactive)

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

def getTrackDescriptor(track):
    artist = getFormattedArtists(track['artists'])
    title = track['name']
    trackNumber = track['track_number']
    album = track['album']['name']
    coverURL = track['album']['images'][0]['url']
    fileName = "{:02d} {}".format(trackNumber, 
                                  remove_illegal_characters(title))
    durationInMs = track['duration_ms']

    return TrackDescriptor( trackNumber, title, artist, album,
                            coverURL, fileName, durationInMs )


#-------------------------------------------------------------------------------

def process_tracks(tracks, ripped_file, sourceFilePath, curr_start_pos, playlist_name):
    for index, item in enumerate(tracks['items']):
        # first check if we are not trying to export out of range
        if curr_start_pos == len(ripped_file):
            print("EOF reached, aborting!")
            return

        # store track metadata
        track = item['track']
        descriptor = getTrackDescriptor(track)

        print("----- %s - %s -----" % (descriptor.artist, descriptor.title))

        # Analysis phase to find the end of the track based on silence
        print("* ANALYZING...")
        silence_found, computed_end = get_nearest_silence(ripped_file,
            curr_start_pos + descriptor.duration)
        computed_duration = computed_end - curr_start_pos
        if not silence_found:
            print("ERROR: Falling back to manual mode")
            print("** Original track duration : %s" % (
                format_ms_time(descriptor.duration)))
        else:
            duration_delta = computed_duration - descriptor.duration
            more = "" if duration_delta >= 0 else "-"
            duration_delta = math.sqrt(duration_delta * duration_delta)
            print("** Difference with original duration : %s%s" % (more,
                format_ms_time(duration_delta)))

        # export and compute the next starting point
        curr_start_pos = export_slice(ripped_file, sourceFilePath, curr_start_pos, computed_end, descriptor.filename, not silence_found)

        # write metadata
        descriptor.filename += ".mp3"
        write_tags(descriptor)

    return curr_start_pos

#-------------------------------------------------------------------------------

def write_tags(descriptor):
    print("* TAGGING...")
    audioFile = eyed3.load(descriptor.filename)

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
    sourceFilePath = Path(ripped_filepath)
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
            curr_start_pos = process_tracks(tracks, ripped_file, sourceFilePath, curr_start_pos,
                                            playlist_name)
            while tracks['next']:
                tracks = sp.next(tracks)
                curr_start_pos = process_tracks(tracks, ripped_file, sourceFilePath, 
                                               curr_start_pos, playlist_name)

#-------------------------------------------------------------------------------
