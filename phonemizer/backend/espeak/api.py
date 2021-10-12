# Copyright 2015-2021 Mathieu Bernard
#
# This file is part of phonemizer: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# Phonemizer is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with phonemizer. If not, see <http://www.gnu.org/licenses/>.
"""Low-level bindings to the espeak-ng API"""

import ctypes
import pathlib
import shutil
import sys
import tempfile
import weakref

import dlinfo

from phonemizer.backend.espeak.voice import EspeakVoice


class EspeakAPI:
    def __init__(self, library):
        self._library = None
        self._tempdir = tempfile.mkdtemp()

        # properly exit when the wrapper object is destoyed (see
        # https://docs.python.org/3/library/weakref.html#comparing-finalizers-with-del-methods)
        weakref.finalize(self, self._terminate)

        # Because the library is not designed to be wrapped nor to be used in
        # multithreaded/multiprocess contexts (massive use of global variables)
        # we need a copy of the original library for each instance of the
        # wrapper... (see "man dlopen" on Linux/MacOS: we cannot load two times
        # the same library because a reference is then returned by dlopen). The
        # tweak is therefore to make a copy of the original library in a
        # different (temporary) directory.
        try:
            # load the original library in order to retrieve its full path
            espeak = ctypes.cdll.LoadLibrary(library)
            library_path = self._shared_library_path(espeak)
            del espeak
        except OSError as error:
            raise RuntimeError(
                f'failed to load espeak library: {str(error)}') from None

        espeak_copy = pathlib.Path(self._tempdir) / library_path.name
        shutil.copy(library_path, espeak_copy, follow_symlinks=False)

        # finally load the library copy and initialize it. 0x02 is
        # AUDIO_OUTPUT_SYNCHRONOUS in the espeak API
        self._library = ctypes.cdll.LoadLibrary(espeak_copy)
        if self._library.espeak_Initialize(0x02, 0, None, 0) <= 0:
            raise RuntimeError(
                'failed to initialize espeak shared library')

        # the path to the original one (the copy is considered an
        # implementation detail and is not exposed)
        self._library_path = library_path

    def _terminate(self):
        # clean up the espeak library allocated memory and the tempdir
        # containing the copy of the library
        if self._library:
            self._library.espeak_Terminate()
        shutil.rmtree(self._tempdir)

    @property
    def library_path(self):
        return self._library_path

    @staticmethod
    def _shared_library_path(library):
        """Returns the absolute path to `library`

        This function is cross-platform and works for Linux, MacOS and Windows.
        Raises a RuntimeError if the library path cannot be retrieved

        """
        # Windows
        if sys.platform == 'win32':  # pragma: nocover
            # pylint: disable=protected-access
            return pathlib.Path(library._name).resolve()

        # Linux or MacOS
        try:
            return pathlib.Path(dlinfo.DLInfo(library).path).resolve()
        except Exception:
            raise RuntimeError(
                f'failed to retrieve the path to {library} library') from None

    def info(self):
        f_info = self._library.espeak_Info
        f_info.restype = ctypes.c_char_p
        data_path = ctypes.c_char_p()
        version = f_info(ctypes.byref(data_path))
        return version, data_path.value

    def list_voices(self, name):
        f_list_voices = self._library.espeak_ListVoices
        f_list_voices.argtypes = [ctypes.POINTER(EspeakVoice.Struct)]
        f_list_voices.restype = ctypes.POINTER(
            ctypes.POINTER(EspeakVoice.Struct))
        return f_list_voices(name)

    def set_voice_by_name(self, name):
        f_set_voice_by_name = self._library.espeak_SetVoiceByName
        f_set_voice_by_name.argtypes = [ctypes.c_char_p]
        return f_set_voice_by_name(name)

    def get_current_voice(self):
        f_get_current_voice = self._library.espeak_GetCurrentVoice
        f_get_current_voice.restype = ctypes.POINTER(EspeakVoice.Struct)
        return f_get_current_voice().contents

    def text_to_phonemes(self, text_ptr, text_mode, phonemes_mode):
        f_text_to_phonemes = self._library.espeak_TextToPhonemes
        f_text_to_phonemes.restype = ctypes.c_char_p
        f_text_to_phonemes.argtypes = [
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.c_int,
            ctypes.c_int]
        return f_text_to_phonemes(text_ptr, text_mode, phonemes_mode)

    def set_phoneme_trace(self, mode, file_pointer):
        f_set_phoneme_trace = self._library.espeak_SetPhonemeTrace
        f_set_phoneme_trace.argtypes = [
            ctypes.c_int,
            ctypes.c_void_p]
        f_set_phoneme_trace(mode, file_pointer)

    def synthetize(self, text, size, mode):
        f_synthetize = self._library.espeak_Synth
        f_synthetize.argtypes = [
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_uint,
            ctypes.c_int,  # position_type
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_uint),
            ctypes.c_void_p]
        return f_synthetize(text, size, 0, 1, 0, mode, None, None)
