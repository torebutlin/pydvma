# tkinter import common modules
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox

# tkinter matplotlib backend
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from matplotlib.ticker import AutoLocator

import copy
import numpy as np
import threading




# #import logging
# #logging.basicConfig(filename='example.log',level=logging.DEBUG)
# #%%

# from . import plotting
# from . import datastructure
# from . import acquisition
# from . import analysis
# from . import streams
# from . import file
# from . import modal
# from . import options
import time
import sys, os

#%%
import tkinter as tk
from tkinter import ttk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

class Logger(tk.Tk):
    def __init__(self):
        super().__init__()

        # Set up the main window
        self.title("Logger")
        self.geometry("800x600")
        self.iconphoto(True, tk.PhotoImage(file='./icon.png'))
        
        # Create grid of frames
        self.frame_main = ttk.Frame(self)
        self.frame_main.grid(column=0, row=0, sticky=(tk.N, tk.W, tk.E, tk.S))
        

        # Create left frame
        self.left_frame = ttk.Frame(self.frame_main)
        self.left_frame.grid(column=0, row=0, sticky=(tk.N, tk.W, tk.E, tk.S))
        
        # Create right frame
        self.right_frame = ttk.Frame(self.frame_main)
        self.right_frame.grid(column=2, row=0, sticky=(tk.N, tk.W, tk.E, tk.S))
        
        
        # Create middle frame
        self.middle_frame = ttk.Frame(self.frame_main)
        self.middle_frame.grid(column=1, row=0, sticky=(tk.N, tk.W, tk.E, tk.S))
        
        
        # Create top middle frame
        self.top_middle_frame = ttk.Frame(self.middle_frame)
        self.top_middle_frame.grid(column=0, row=0, sticky=(tk.N, tk.W, tk.E, tk.S))
        
        # Create centre middle frame
        self.centre_middle_frame = ttk.Frame(self.middle_frame)
        self.centre_middle_frame.grid(column=0, row=1, sticky=(tk.N, tk.W, tk.E, tk.S))
        
        
        # Create bottom middle frame
        self.bottom_middle_frame = ttk.Frame(self.middle_frame)
        self.bottom_middle_frame.grid(column=0, row=1, sticky=(tk.N, tk.W, tk.E, tk.S))
        
        

        self.setup_left_frame()
        self.mainloop()

    def setup_left_frame(self):
        # add buttons
        self.button_start = ttk.Button(self.left_frame, text="Start")
        self.button_start.grid(column=0, row=0, sticky=(tk.N, tk.W, tk.E, tk.S))
        
        
    
    def show(self):
        self.mainloop()
        self.lift()


# %%
