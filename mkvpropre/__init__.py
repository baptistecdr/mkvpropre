"""Normalize MKV episodes and movies: track order, names, languages, flags, attachments and tags.

Pipeline, per file:
  probe     read the file (mkvmerge -J) and analyse its subtitles   -> MediaFile
  plan      decide the target state of every track (pure, no I/O)   -> Plan
  apply     reorder with a lossless remux if needed, then set only the
            properties that differ with mkvpropedit

Modules, each depending only on the ones above it:
  config     languages, defaults and thresholds
  model      Track, MediaFile, ... (what a file contains)
  tools      running MKVToolNix
  files      safe file operations (unpredictable temp files, no-overwrite moves)
  subtitles  subtitle parsing and per-codec analysers
  probe      file -> MediaFile
  plan       MediaFile -> Plan
  apply      Plan -> changes on disk
  lookup     title, VO and English names of episodes and movies, with FileBot
  library    library paths and safe moves (--library)
  completion shell completion scripts (--completion)
  cli        command line
"""

__version__ = "0.3.0"
