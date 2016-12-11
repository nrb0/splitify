#!/usr/local/bin/python

import eyed3
import math
import os
import pydub
import sys
import spotipy
import spotipy.util as util
import urllib

def ask_question(message, possible_answers=[]):
    yes_no_question = len(possible_answers) == 0

    if yes_no_question:
        sys.stdout.write("%s [Y/n]? " % message)
    else:
        print "%s : " % message
        answer_index = 1
        for answer in possible_answers:
            print "%d. %s" % (answer_index, str(answer))
            answer_index += 1

    user_input = raw_input()

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
            print "Something"
    print "Invalid choice"
    return ask_question(message, possible_answers)

def ask_int_input(message):
    sys.stdout.write("%s : " % message)
    user_input = raw_input()
    if user_input == "":
        return 0

    try:
        value = int(user_input)
        return value
    except ValueError:
        print "Invalid input"
        return ask_int_input(message)

    print "Invalid choice"
    return ask_question(message, possible_answers)

def removeIllegalCharacters(name):
    remove_punctuation_map = dict((ord(char), None) for char in '\/*?:"<>|')
    return name.translate(remove_punctuation_map)

def format_ms_time(duration_ms, with_ms=False):
    s, ms = divmod(duration_ms, 1000)
    m, s = divmod(s, 60)
    if with_ms:
        return "%02d:%02d:%03d" % (m, s, ms)
    else:
        return "%02d:%02d" % (m, s)

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
            #print "** from %s to %s" % (format_ms_time(current_pos), format_ms_time(current_last_pos))
            for index in range(current_pos, current_last_pos):
                window_slice = audio[index:index + analysis_window]
                if window_slice.rms == 0:
                    return True, index
    print "ERROR: No silence were found"
    return False, position

def export_slice(ripped_file, start_pos, end_pos, file_name, interactive):
    full_path = file_name
    local_end_position = end_pos
    end_of_file = local_end_position >= len(ripped_file)

    if end_of_file:
        local_end_position = len(ripped_file) - 1
        full_path = "(INCOMPLETE) " + file_name

    print "* EXPORTING..."
    print "** from %s to %s ..." % (format_ms_time(start_pos, True), format_ms_time(local_end_position, True))
    audio_slice = ripped_file[start_pos:local_end_position]
    audio_slice.export(full_path, format="mp3")

    if end_of_file or not interactive or interactive and ask_question("Is the export correct"):
        return local_end_position + 1
    else:
        os.remove(full_path)
        start_offset = ask_int_input("Start offset (in ms)")
        end_offset = ask_int_input("End offset (in ms)")
        return export_slice(ripped_file, start_pos + start_offset, end_pos + end_offset, full_path, interactive)

def processTracks(tracks, ripped_file, totalLength, curr_start_pos, playlist_name):
    for index, item in enumerate(tracks['items']):

        # first check if we are not trying to export out of range
        if curr_start_pos == len(ripped_file):
            print "EOF reached, aborting!"
            return

        # store track metadata
        track = item['track']
        track_artist = track['artists'][0]['name']
        track_title = track['name']
        track_picture_url = track['album']['images'][0]['url']
        track_filepath = " %02d %s - %s.mp3" % (index+1, removeIllegalCharacters(track_artist), removeIllegalCharacters(track_title))
        track_duration_ms = track['duration_ms']

        print "----- %s - %s -----" % (track_artist, track_title)

        # if os.path.exists(track_filepath) and ask_question("The file already exists, skip"):
        #     curr_file = pydub.AudioSegment.from_mp3(track_filepath)
        #     curr_start_pos += len(curr_file)
        #     print "Skipping playhead to %s" % format_ms_time(curr_start_pos, True)
        #     continue

        # Compute track end
        print "* ANALYZING..."
        silence_found, computed_end = get_nearest_silence(ripped_file, curr_start_pos + track_duration_ms)
        computed_duration = computed_end - curr_start_pos
        if not silence_found:
            print "ERROR: Falling back to manual mode"
            print "** Original track duration : %s" % format_ms_time(track_duration_ms, True)
        else:
            duration_delta = computed_duration - track_duration_ms
            more = "" if duration_delta >= 0 else "-"
            duration_delta = math.sqrt(duration_delta * duration_delta)
            print "** Duration delta : %s%s" % (more, format_ms_time(duration_delta, True))

        # export and compute the next starting point
        curr_start_pos = export_slice(ripped_file, curr_start_pos, computed_end, track_filepath, not silence_found)

        # write metadata
        write_tags(track_filepath, track_artist, track_title, playlist_name, track_picture_url)

def write_tags(file_path, artist, title, album, pic_url=""):
    print ("* TAGGING...")
    audio_file = eyed3.load(file_path)
    if audio_file.tag is None:
        audio_file.initTag()
        audio_file.tag.save()
    audio_file.tag.artist = unicode(artist)
    audio_file.tag.title = unicode(title)
    audio_file.tag.album = unicode(album)
    if pic_url != "":
        urllib.urlretrieve(pic_url, "pic.jpeg")
        pic = open("pic.jpeg", "rb").read()
        audio_file.tag.images.set(3, pic, "image/jpeg", u"cover")
        os.remove("pic.jpeg")
    audio_file.tag.save()


if __name__ == '__main__':
    if len(sys.argv) > 1:
        userName = sys.argv[1]
        playlistName = sys.argv[2]
        ripped_filePath = sys.argv[3]
    else:
        #print "usage: user_playlists.py [username] [spotifyPlaylistName] [path/to/ripped/mp3]"
        sys.exit()
    # Start by getting the ripped file and preparing some data for iterating
    ripped_file = pydub.AudioSegment.from_mp3(ripped_filePath)
    totalLength = len(ripped_file)
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
            processTracks(tracks, ripped_file, totalLength, currentStartPosition, playlistName)
            while tracks['next']:
                tracks = sp.next(tracks)
                processTracks(tracks, ripped_file, totalLength, currentStartPosition, playlistName)
