VOJTAMAUR.CZ — SSTV EDITION
=============================

WHAT IS THIS?
-------------

These WAV files are an audio-encoded visual edition of:

    https://vojtamaur.cz/

They are not music, speech, a ZIP archive, or a conventional data backup.

The website was rendered into a sequence of low-resolution pages. Each page was
then encoded as a standard SSTV (Slow-Scan Television) image transmission.

Decode the audio with an SSTV receiver that supports PD120 and the pages of the
website will appear visually, one after another.

    WAV audio
        ->
    SSTV PD120 decoder
        ->
    visible pages of vojtamaur.cz


FILES
-----

Decode the volumes in this order:

    combined-with-gaps_001.wav
    combined-with-gaps_002.wav
    combined-with-gaps_003.wav
    combined-with-gaps_004.wav
    combined-with-gaps_005.wav
    combined-with-gaps_006.wav

Total size:

    21,186,571,264 bytes


TECHNICAL FORMAT
----------------

SSTV mode:

    PD120

Image size:

    640 x 496 pixels

Each page is transmitted as its own SSTV frame and includes its own VIS mode
identification signal.

There is approximately 1 second of silence between consecutive frames.

A PD120 frame takes roughly 126 seconds to transmit. Decoding the complete
archive therefore happens in real time. This is intentional.


HOW TO VIEW THE WEBSITE
-----------------------

You need an SSTV decoder that supports PD120.

The archive was successfully tested with MMSSTV on Windows.

Basic procedure:

    1. Play one of the WAV files at normal speed.

    2. Route the computer's playback audio into the SSTV decoder.
       On Windows this can be done with Stereo Mix, an audio loopback device,
       or a virtual audio cable.

    3. Set the SSTV receiver to automatic mode detection.

    4. Let the receiver detect the VIS signal at the beginning of each frame.

    5. The page will be drawn progressively, line by line.

    6. After one page finishes, the next VIS signal identifies the following
       PD120 frame and the next page begins.


TESTED MMSSTV SETTINGS
----------------------

Main RX window:

    RX Mode:        Auto
    Auto history:   ON

Option -> Setup MMSSTV -> RX:

    Auto start:     VIS only
    Auto restart:   ON
    Auto resync:    ON
    Auto stop:      OFF

Option -> Setup MMSSTV -> Misc:

    Sound Card -> In:
        Select the loopback / Stereo Mix input.

        If Stereo Mix is configured as the default Windows recording device,
        "Default" can be used here.

On Windows, Stereo Mix may need to be enabled first:

    Control Panel
        -> Sound
        -> Recording
        -> Stereo Mix
        -> Enable
        -> Set as Default Device

Then play the WAV file and watch the RX window. The pages should reconstruct
themselves live.


STARTING IN THE MIDDLE OF A FILE
--------------------------------

You do not need to start at the beginning of a WAV volume.

You may seek to an arbitrary point.

If playback begins in the middle of an SSTV image, that partial image may not
decode correctly. Simply keep playing.

At the next VIS signal the receiver is told that a new PD120 frame is beginning,
and normal decoding should resume from that page.


PLAYBACK NOTES
--------------

Use the original WAV files whenever possible.

Do not intentionally change playback speed or pitch.

Avoid unnecessary lossy transcoding or aggressive audio processing. SSTV is
robust, but the most reliable reconstruction comes from the original audio at
its original timing.


OTHER SSTV SOFTWARE
-------------------

MMSSTV is not required in principle.

Any standard SSTV receiver capable of decoding PD120 can be used.

Open-SSTV was used successfully for encoding and for decoding individual SSTV
images. For the long continuous multi-image WAV volumes, MMSSTV was practically
verified to work with automatic VIS detection and Auto restart.


WHAT YOU SHOULD SEE
-------------------

Successful decoding produces a sequence of pages representing the textual and
visual content of vojtamaur.cz.

The received images may contain characteristic SSTV artifacts such as slight
color fringing, timing imperfections, edge noise, or other analog-looking
distortions.

These are natural consequences of the SSTV transmission and decoding process.
They are not decorative filters added to the source pages.


ARCHIVAL INTENT
---------------

This edition deliberately represents the website in a different medium.

Instead of preserving only the original web technologies, the content is also
represented as a sequence of standardized visual radio transmissions stored as
ordinary audio.

The intended recovery path is:

    find the WAV files
        ->
    identify them as SSTV PD120
        ->
    decode them with a standard SSTV receiver
        ->
    read the website visually

No copy of the original website, browser engine, or custom decoder is required
to interpret the visual content of this edition.


SOURCE
------

Website:

    https://vojtamaur.cz/

Edition:

    vojtamaur.cz SSTV Edition

Encoding mode:

    SSTV PD120


ČESKY — STRUČNĚ
---------------

Tyto WAV soubory obsahují stránky webu vojtamaur.cz zakódované jako standardní
SSTV PD120 obrazové přenosy.

Použij SSTV dekodér s podporou PD120, například MMSSTV. Přehraj WAV v normální
rychlosti, pošli zvuk do dekodéru přes Stereo Mix / loopback a nech zapnutou
automatickou detekci VIS a automatický restart příjmu.

Každý další VIS označuje začátek nové stránky. Pokud začneš přehrávat uprostřed
souboru, stačí počkat na následující VIS a další obraz se začne normálně
vykreslovat.
