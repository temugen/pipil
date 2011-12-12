# Copyright (C) 2011 Brad Misik
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of
# this software and associated documentation files (the "Software"), to deal in
# the Software without restriction, including without limitation the rights to
# use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
# of the Software, and to permit persons to whom the Software is furnished to do
# so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# Set to False to test alternative image processor
use_PIL = True

import string
from multiprocessing import Process
import imp
import os
import tempfile
import subprocess
from time import sleep
import atexit

# Remove our temporary files when the module is unloaded
temp_files = []
def cleanup_temp():
  for filename in temp_files:
    os.remove(filename)
atexit.register(cleanup_temp)

try:
  # Do not attempt an import here
  # Tkinter can't be loaded in a process and its subprocesses simultaneously
  imp.find_module('Tkinter')
  _has_Tk = True
except:
  _has_Tk = False

def _pil_open(filename):
  image = PILImage.open(filename)
  data = image.getdata()
  # Only get the RGB components in case the image is ARGB
  data = [tuple(color[len(color) - 3:]) for color in data]
  return (data, image.size)

def _nopil_open(filename):
  # Run a java utility to print out the pixels of the image to stdout
  command = ['java', '-jar', 'ImagePiper.jar', 'read', filename]
  image_piper = subprocess.Popen(command, stdout=subprocess.PIPE)

  # Read the output from ImagePiper
  stdout, stderr = image_piper.communicate()
  lines = stdout.splitlines()
  # Read the encoding from the first line of output
  radix = int(lines.pop(0))
  # Read the width and the height from the second line of output
  w, h = tuple(int(x, radix) for x in lines.pop(0).split())
  # Read the pixels line by line, with each line corresponding to a line from the image
  data = [Color.int_to_rgb(int(pixel, radix)) for line in lines for pixel in line.split()]
  return (data, (w, h))

def _pil_save(image, filename):
  w, h = image.size
  pil_image = PILImage.new("RGB", (w, h))
  pil_image.putdata(image.data)
  pil_image.save(filename, "png")

def _nopil_save(image, filename):
  # Run a java utility to read in the pixels of the image and save them to a file
  command = ['java', '-jar', 'ImagePiper.jar', 'write', filename]
  image_piper = subprocess.Popen(command, stdout=subprocess.PIPE, stdin=subprocess.PIPE)

  # Read the encoding from ImagePiper and create a codec for it
  radix = int(image_piper.stdout.readline())
  codec = IntegerCodec()
  # Write the width and the height
  w, h = image.size
  image_piper.stdin.write("%s %s\n" % (codec.encode(w, radix), codec.encode(h, radix)))
  # Write the pixels line by line
  pixels = map(lambda pixel: codec.encode(Color.rgb_to_int(pixel), radix), image.data)
  lines = [" ".join(pixels[image._get_index((0, line)):image._get_index((w, line))]) for line in range(h)]
  image_piper.stdin.write("\n".join(lines))
  # Flush the writes
  image_piper.communicate()

try:
  from PIL import Image as PILImage
  _has_PIL = True
except:
  _has_PIL = False

class IntegerCodec:
  def __init__(self):
    self._base_list = string.digits + string.letters + '_@'

  def decode(self, int_string, radix):
    return int(int_string, radix)

  def encode(self, integer, radix):
    # Only encode absolute value of integer
    sign = ''
    if integer < 0:
      sign = '-'
      integer = abs(integer)

    int_string = ''
    while integer != 0:
      int_string = self._base_list[integer % radix] + int_string
      integer /= radix

    return sign + int_string

class Color:
  def __init__(self, color):
    if type(color) is type(0):
      self.color = Color.int_to_rgb(color)
    else:
      self.color = color

  def as_int(self):
    return Color.rgb_to_int(self.color)

  def as_rgb(self):
    return self.color

  @staticmethod
  def int_to_rgb(rgb_int):
    r = (rgb_int >> 16) & 255
    g = (rgb_int >> 8) & 255
    b = rgb_int & 255
    return (r, g, b)

  @staticmethod
  def rgb_to_int(rgb):
    r, g, b = rgb
    rgb_int = r
    rgb_int = (rgb_int << 8) + g
    rgb_int = (rgb_int << 8) + b
    return rgb_int

class Image:
  def __init__(self, *args):
    if type(args[0]) is type("string"):
      # Assume we were passed a filename
      self._open(args[0])
    elif type(args[0]) is type(self):
      # Assume we were passed another image
      self._copy(args[0])
    else:
      # Assume we were passed a size tuple and possibly a color
      self._create(*args)

  def _open(self, filename):
    if _has_PIL and use_PIL:
      _opener = _pil_open
    else:
      _opener = _nopil_open

    self.data, self.size = _opener(filename)

  def _create(self, size, color = (0, 0, 0)):
    w, h = self.size = size
    w, h = int(w), int(h)
    self.data = [color] * w * h

  def _copy(self, image):
    self.size = image.size
    self.data = image.data[:]

  def _get_index(self, loc):
    # Convert an (x, y) pair to a 1-dimensional index
    x, y = loc
    x, y = int(x), int(y)
    w, h = self.size
    return y * w + x

  def getpixel(self, loc):
    return self.data[self._get_index(loc)]

  def putpixel(self, loc, color):
    self.data[self._get_index(loc)] = color

  def temp_file(self):
    handle, filename = tempfile.mkstemp()
    self.save(filename)
    os.close(handle)
    temp_files.append(filename)
    return filename

  def _show_in_os(self):
    # Save the image to a temporary file for another process to read
    filename = self.temp_file()

    if os.name == 'nt':
      os.startfile(filename)
    else:
      # Assume we are on a mac and attempt to use the open command
      retcode = subprocess.call(['open', filename])

      if retcode is not 0:
        # The open command failed, so assume we are on Linux
        subprocess.call(['xdg-open', filename])

  def show(self, default=False, wait=False):
    # Open the image using the user's default imaging viewing application, cannot wait
    if default or not _has_Tk:
      self._show_in_os()
    else:
      # Open the file using our own image viewer
      viewer = ImageViewer(self, wait)

  def save(self, filename):
    if _has_PIL and use_PIL:
      _saver = _pil_save
    else:
      _saver = _nopil_save

    _saver(self, filename)

  @staticmethod
  def new(mode, size, color = (0, 0, 0)):
    #ignore mode for now
    return Image(size, color)

  def copy(self):
    return Image(self)

  def __ne__(self, other):
    w1, h1 = self.size
    w2, h2 = other.size
    if w1 != w2 or h1 != h2:
      return True
    for i in range(len(self.data)):
      if self.data[i] != other.data[i]:
        return True
    return False

  def __eq__(self, other):
    return not (self != other)


class ImageViewer():
  def __init__(self, image, block=False):
    self.Tkphoto = ImageViewer._image_to_Tkphoto(image)
    p = Process(target=self.run)
    p.start()

    # Wait for the process to finish if the user requests a block
    if block is True:
      p.join()

  @staticmethod
  def _image_to_Tkphoto(image):
    w, h = image.size
    pixels = map(lambda pixel: "#%02x%02x%02x" % pixel, image.data)
    lines = ["{" + " ".join(pixels[image._get_index((0, line)):image._get_index((w, line))]) + "}" for line in range(h)]
    fill = " ".join(lines)
    return (fill, (w, h))

  def run(self):
    fill, (w, h) = self.Tkphoto

    import Tkinter
    self.root = Tkinter.Tk()
    self.root.title("Info 103 Image Viewer")
    self.root.configure(width=w, height=h)

    # Convert our image to a PhotoImage used by Tkinter
    photo = Tkinter.PhotoImage(width=w, height=h)
    photo.put(fill)

    label = Tkinter.Label(self.root, image=photo)
    label.pack()

    # Use the alternate main loop defined below if IDLE has problems
    '''
    while True:
      try:
        self.root.update()
      except:
        break
    '''
    self.root.mainloop()
  
