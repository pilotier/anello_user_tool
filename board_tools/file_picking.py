from os import devnull, listdir, path
from contextlib import redirect_stdout
from tkinter import Tk
from tkinter.filedialog import askopenfilename, askopenfilenames, askdirectory

# file picker wrappers to prevent extra windows, focus shift, extra prints


# wrap askopenfilename - picks one file and returns the name
# this passes all the arguments to askopenfilename
def pick_one_file(*args, **kwargs):
    with open(devnull, "w") as f, redirect_stdout(f):  # prevent prints inside
        root = Tk()
        root.withdraw()  # prevent extra tkinter window
        file_path = askopenfilename(*args, **kwargs)
        root.destroy()  # sends focus back to cmd window
    return file_path


# askopenfilenames(multiple file pick) with same fixes
def pick_multiple_files(*args, **kwargs):
    with open(devnull, "w") as f, redirect_stdout(f):
        root = Tk()
        root.withdraw()
        file_paths = askopenfilenames(*args, **kwargs)
        root.destroy()
    return file_paths


def pick_one_directory(*args, **kwargs):
    with open(devnull, "w") as f, redirect_stdout(f):
        root = Tk()
        root.withdraw()
        location = askdirectory(*args, **kwargs)
        root.destroy()
    return location


# return all the file paths inside one directory
def pick_one_dir_file_paths(initialdir=None, title=None):
    folder_path = pick_one_directory(initialdir, title)
    return [path.join(folder_path, file_name) for file_name in listdir(folder_path)]
