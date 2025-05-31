import os
import requests
import tkinter as tk
from tkinter import messagebox, filedialog, scrolledtext
from tkinter import ttk
import threading
import time
from datetime import datetime
import webbrowser
from PIL import Image, ImageTk
import io
from dotenv import load_dotenv

load_dotenv() # Load variables from .env file

# Replace with your Google API key and Custom Search Engine ID
API_KEY = os.getenv("API_KEY")
CSE_ID = os.getenv("CSE_ID")

# Global variables for controlling the search
is_paused = False
is_stopped = False
current_preview = None

# Color scheme
COLORS = {
    "primary": "#3498db",      # Blue
    "primary_dark": "#2980b9", # Dark Blue
    "secondary": "#2ecc71",    # Green
    "accent": "#e74c3c",       # Red
    "bg_dark": "#34495e",      # Dark Slate
    "bg_light": "#ecf0f1",     # Light Gray
    "text_dark": "#2c3e50",    # Very Dark Blue
    "text_light": "#ffffff"    # White
}

# Define filter options
IMG_SIZE_OPTIONS = ["any", "huge", "icon", "large", "medium", "small", "xlarge", "xxlarge"]
IMG_TYPE_OPTIONS = ["any", "clipart", "face", "lineart", "stock", "photo", "animated"]
IMG_COLOR_TYPE_OPTIONS = ["any", "color", "gray", "mono"]
FILE_TYPE_OPTIONS = ["any", "bmp", "gif", "jpg", "png", "svg", "webp"] # Added webp
SAFE_SEARCH_OPTIONS = ["off", "active", "high", "medium"]

def search_images(query, num_results=10, img_size="any", img_type="any", img_color_type="any", file_type="any", safe_search="off"):
    url = f"https://customsearch.googleapis.com/customsearch/v1"
    params = {
        'q': query,
        'cx': CSE_ID,
        'key': API_KEY,
        'searchType': 'image',
        'num': num_results
    }

    # Add filters if they are not "any" or "off" (for safe search)
    if img_size != "any":
        params['imgSize'] = img_size.upper() # API expects uppercase for some
    if img_type != "any":
        params['imgType'] = img_type
    if img_color_type != "any":
        params['imgColorType'] = img_color_type
    if file_type != "any":
        params['fileType'] = file_type
    if safe_search != "off": # "off" is the default, no need to send
        params['safe'] = safe_search

    response = requests.get(url, params=params)
    if response.status_code == 200:
        return response.json().get('items', [])
    else:
        messagebox.showerror("Error", f"Failed to fetch images: {response.status_code}")
        return []

def save_images(image_items, save_directory, query):
    if not os.path.exists(save_directory):
        os.makedirs(save_directory)
    
    query_directory = os.path.join(save_directory, query.replace(" ", "_"))
    if not os.path.exists(query_directory):
        os.makedirs(query_directory)
    
    saved_count = 0
    failed_count = 0
    
    for i, item in enumerate(image_items):
        if is_stopped:
            break
        while is_paused:
            time.sleep(0.5)
            
        image_url = item['link']
        try:
            # Update preview if available
            if hasattr(root, 'preview_label'):
                display_preview(image_url)
                
            response = requests.get(image_url, timeout=10)
            if response.status_code == 200:
                # Generate a more descriptive filename
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                image_name = f"{query.replace(' ', '_')}_{i+1}_{timestamp}.jpg"
                image_path = os.path.join(query_directory, image_name)
                
                with open(image_path, 'wb') as f:
                    f.write(response.content)
                log(f"✓ Saved {image_name}", "success")
                saved_count += 1
            else:
                log(f"✗ Failed to download image #{i+1}: HTTP {response.status_code}", "error")
                failed_count += 1
        except Exception as e:
            log(f"✗ Error downloading image #{i+1}: {str(e)[:100]}", "error")
            failed_count += 1
    
    return saved_count, failed_count

def display_preview(image_url):
    global current_preview
    try:
        response = requests.get(image_url)
        if response.status_code == 200:
            image_data = Image.open(io.BytesIO(response.content))
            # Resize image to fit preview area
            image_data.thumbnail((300, 200))
            photo = ImageTk.PhotoImage(image_data)
            
            # Save reference to prevent garbage collection
            current_preview = photo
            
            preview_label.config(image=photo)
            preview_label.image = photo
    except Exception as e:
        # If preview fails, show placeholder
        preview_label.config(image='', text="Preview unavailable")

def on_search():
    global is_paused, is_stopped
    is_paused = False
    is_stopped = False
    
    # Reset buttons state
    pause_button.config(text="Pause", state=tk.NORMAL, bg=COLORS["secondary"])
    stop_button.config(state=tk.NORMAL, bg=COLORS["accent"])
    search_button.config(state=tk.DISABLED)

    # Get the save directory
    save_directory = save_dir_entry.get()
    if not save_directory:
        save_directory = filedialog.askdirectory()
        if not save_directory:
            search_button.config(state=tk.NORMAL)
            return
        save_dir_entry.delete(0, tk.END)
        save_dir_entry.insert(0, save_directory)
    
    # Get search queries
    queries = query_text.get("1.0", tk.END).splitlines()
    queries = [q for q in queries if q.strip()]
    
    if not queries:
        messagebox.showwarning("Warning", "Please enter at least one search query")
        search_button.config(state=tk.NORMAL)
        return
    
    # Get filter values
    selected_img_size = img_size_combobox.get()
    selected_img_type = img_type_combobox.get()
    selected_img_color_type = img_color_type_combobox.get()
    selected_file_type = file_type_combobox.get()
    selected_safe_search = safe_search_combobox.get()

    # Get number of images
    try:
        num_images = int(num_images_entry.get())
        if num_images <= 0:
            raise ValueError("Number must be positive")
    except ValueError:
        messagebox.showwarning("Warning", "Please enter a valid number of images")
        search_button.config(state=tk.NORMAL)
        return
    
    output_text.delete(1.0, tk.END)  # Clear previous output
    
    # Setup progress tracking
    progress['maximum'] = len(queries) * num_images
    progress['value'] = 0
    
    status_label.config(text="Status: Running...", fg=COLORS["secondary"])
    
    # Create and start worker thread
    def search_thread():
        total_saved = 0
        total_failed = 0
        
        start_time = time.time()
        
        for i, query in enumerate(queries):
            if is_stopped:
                break
                
            if query.strip():
                log(f"🔍 Searching for: {query}", "heading")
                image_items = search_images(
                    query,
                    num_images,
                    img_size=selected_img_size,
                    img_type=selected_img_type,
                    img_color_type=selected_img_color_type,
                    file_type=selected_file_type,
                    safe_search=selected_safe_search
                )
                
                if image_items:
                    log(f"Found {len(image_items)} images for '{query}'", "info")
                    saved, failed = save_images(image_items, save_directory, query)
                    total_saved += saved
                    total_failed += failed
                    folder_path = os.path.join(save_directory, query.replace(" ", "_"))
                    log(f"• Images saved to: {folder_path}", "info")
                else:
                    log(f"No images found for '{query}'", "warning")
            
            # Update progress
            progress['value'] = (i + 1) * num_images
            
        end_time = time.time()
        duration = round(end_time - start_time, 1)
        
        log(f"\n==== SUMMARY ====", "heading")
        log(f"• Queries processed: {len(queries)}", "info")
        log(f"• Images saved: {total_saved}", "success")
        log(f"• Failed downloads: {total_failed}", "error" if total_failed > 0 else "info")
        log(f"• Time taken: {duration} seconds", "info")
        log(f"• Save location: {save_directory}", "info")
        
        # Re-enable search button
        search_button.config(state=tk.NORMAL)
        pause_button.config(state=tk.DISABLED)
        stop_button.config(state=tk.DISABLED)
        status_label.config(text="Status: Completed", fg=COLORS["primary"])
        
        # Show completion notification
        if not is_stopped:
            messagebox.showinfo("Complete", f"Search completed. Saved {total_saved} images.")
    
    threading.Thread(target=search_thread, daemon=True).start()

def on_pause():
    global is_paused
    is_paused = not is_paused
    pause_button.config(
        text="Resume" if is_paused else "Pause",
        bg=COLORS["primary"] if is_paused else COLORS["secondary"]
    )
    status_label.config(
        text="Status: Paused" if is_paused else "Status: Running...",
        fg=COLORS["accent"] if is_paused else COLORS["secondary"]
    )

def on_stop():
    global is_stopped
    is_stopped = True
    stop_button.config(state=tk.DISABLED)
    search_button.config(state=tk.NORMAL)
    status_label.config(text="Status: Stopped", fg=COLORS["accent"])

def select_directory():
    directory = filedialog.askdirectory()
    if directory:
        save_dir_entry.delete(0, tk.END)
        save_dir_entry.insert(0, directory)

def open_save_location():
    directory = save_dir_entry.get()
    if directory and os.path.exists(directory):
        # Open file explorer to the directory
        if os.name == 'nt':  # Windows
            os.startfile(directory)
        elif os.name == 'posix':  # macOS and Linux
            webbrowser.open('file:///' + directory)
    else:
        messagebox.showwarning("Warning", "Please select a valid save directory first")

def log(message, level="normal"):
    # Assign tags based on message type
    tags = ()
    if level == "success":
        tags = ("success",)
    elif level == "error":
        tags = ("error",)
    elif level == "warning":
        tags = ("warning",)
    elif level == "info":
        tags = ("info",)
    elif level == "heading":
        tags = ("heading",)
        
    output_text.insert(tk.END, message + "\n", tags)
    output_text.see(tk.END)

def on_closing():
    if not is_stopped and not search_button['state'] == tk.NORMAL:
        if messagebox.askyesno("Quit", "A search is in progress. Do you want to quit anyway?"):
            root.destroy()
    else:
        root.destroy()

# GUI Setup
root = tk.Tk()
root.title("Modern Image Search")
root.geometry("950x700")
root.configure(bg=COLORS["bg_light"])
root.protocol("WM_DELETE_WINDOW", on_closing)

# Custom styles
style = ttk.Style()
style.theme_use('clam')
style.configure("TProgressbar", 
                thickness=25,
                troughcolor=COLORS["bg_light"],
                background=COLORS["primary"])
style.configure("TCombobox",
                fieldbackground="white",
                background=COLORS["bg_light"],
                foreground=COLORS["text_dark"],
                arrowcolor=COLORS["primary"],
                selectbackground=COLORS["primary"],
                selectforeground="white")
style.map('TCombobox', fieldbackground=[('readonly', 'white')])

# Create custom fonts
title_font = ("Helvetica", 16, "bold")
heading_font = ("Helvetica", 12, "bold")
normal_font = ("Helvetica", 10)

# Main container
main_frame = tk.Frame(root, bg=COLORS["bg_light"], padx=20, pady=20)
main_frame.pack(fill=tk.BOTH, expand=True)

# Title
title_label = tk.Label(main_frame, 
                      text="Image Search & Download",
                      font=title_font,
                      bg=COLORS["bg_light"],
                      fg=COLORS["primary"])
title_label.pack(pady=(0, 15))

# Left panel (input controls)
left_panel = tk.Frame(main_frame, bg=COLORS["bg_light"], padx=10, pady=10)
left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

# Right panel (preview)
right_panel = tk.Frame(main_frame, bg=COLORS["bg_dark"], padx=10, pady=10, width=300)
right_panel.pack(side=tk.RIGHT, fill=tk.Y)
right_panel.pack_propagate(False)

# Search queries section
query_frame = tk.LabelFrame(left_panel, text="Search Queries", 
                           font=heading_font,
                           bg=COLORS["bg_light"],
                           fg=COLORS["text_dark"],
                           padx=10, pady=10)
query_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

query_label = tk.Label(query_frame, 
                      text="Enter search queries (one per line):",
                      bg=COLORS["bg_light"],
                      fg=COLORS["text_dark"],
                      font=normal_font)
query_label.pack(anchor=tk.W, pady=(5, 5))

query_text = scrolledtext.ScrolledText(query_frame, 
                                      width=50, height=8,
                                      font=normal_font,
                                      bg="white",
                                      fg=COLORS["text_dark"])
query_text.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

# Settings section
settings_frame = tk.LabelFrame(left_panel, text="Settings", 
                              font=heading_font,
                              bg=COLORS["bg_light"],
                              fg=COLORS["text_dark"],
                              padx=10, pady=10)
settings_frame.pack(fill=tk.X, pady=(0, 10))

# Helper function to create filter dropdowns
def create_filter_dropdown(parent, label_text, options_list):
    frame = tk.Frame(parent, bg=COLORS["bg_light"])
    frame.pack(fill=tk.X, pady=2)
    
    label = tk.Label(frame, 
                     text=label_text,
                     bg=COLORS["bg_light"],
                     fg=COLORS["text_dark"],
                     font=normal_font,
                     width=25,  # Adjusted width
                     anchor=tk.W)
    label.pack(side=tk.LEFT, padx=(0, 10))
    
    combobox = ttk.Combobox(frame, 
                            values=options_list,
                            font=normal_font,
                            state="readonly", # Make it non-editable
                            width=15) # Adjusted width
    combobox.current(0)  # Set default to the first option ("any" or "off")
    combobox.pack(side=tk.LEFT, fill=tk.X, expand=True)
    return combobox

# Number of images
num_images_frame = tk.Frame(settings_frame, bg=COLORS["bg_light"])
num_images_frame.pack(fill=tk.X, pady=5)

num_images_label = tk.Label(num_images_frame, 
                           text="Number of images to download:",
                           bg=COLORS["bg_light"],
                           fg=COLORS["text_dark"],
                           font=normal_font,
                           width=25,
                           anchor=tk.W)
num_images_label.pack(side=tk.LEFT, padx=(0, 10))

num_images_entry = tk.Entry(num_images_frame, 
                           font=normal_font,
                           bg="white",
                           fg=COLORS["text_dark"],
                           width=10)
num_images_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
num_images_entry.insert(0, "10")

# Add filter dropdowns
img_size_combobox = create_filter_dropdown(settings_frame, "Image Size:", IMG_SIZE_OPTIONS)
img_type_combobox = create_filter_dropdown(settings_frame, "Image Type:", IMG_TYPE_OPTIONS)
img_color_type_combobox = create_filter_dropdown(settings_frame, "Image Color Type:", IMG_COLOR_TYPE_OPTIONS)
file_type_combobox = create_filter_dropdown(settings_frame, "File Type:", FILE_TYPE_OPTIONS)
safe_search_combobox = create_filter_dropdown(settings_frame, "Safe Search:", SAFE_SEARCH_OPTIONS)

# Save directory
save_dir_frame = tk.Frame(settings_frame, bg=COLORS["bg_light"])
save_dir_frame.pack(fill=tk.X, pady=5)

save_dir_label = tk.Label(save_dir_frame, 
                         text="Save directory:",
                         bg=COLORS["bg_light"],
                         fg=COLORS["text_dark"],
                         font=normal_font,
                         width=25,
                         anchor=tk.W)
save_dir_label.pack(side=tk.LEFT, padx=(0, 10))

save_dir_entry = tk.Entry(save_dir_frame, 
                         font=normal_font,
                         bg="white",
                         fg=COLORS["text_dark"])
save_dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

browse_button = tk.Button(save_dir_frame, 
                         text="Browse",
                         font=normal_font,
                         bg=COLORS["bg_dark"],
                         fg=COLORS["text_light"],
                         padx=10,
                         command=select_directory)
browse_button.pack(side=tk.LEFT)

# Control buttons
control_frame = tk.Frame(left_panel, bg=COLORS["bg_light"], pady=10)
control_frame.pack(fill=tk.X)

search_button = tk.Button(control_frame, 
                         text="Search and Save Images",
                         font=heading_font,
                         bg=COLORS["primary"],
                         fg=COLORS["text_light"],
                         padx=10, pady=5,
                         command=on_search)
search_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5))

pause_button = tk.Button(control_frame, 
                        text="Pause",
                        font=normal_font,
                        bg=COLORS["secondary"],
                        fg=COLORS["text_light"],
                        padx=10, pady=5,
                        state=tk.DISABLED,
                        command=on_pause)
pause_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)

stop_button = tk.Button(control_frame, 
                       text="Stop",
                       font=normal_font,
                       bg=COLORS["accent"],
                       fg=COLORS["text_light"],
                       padx=10, pady=5,
                       state=tk.DISABLED,
                       command=on_stop)
stop_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(5, 0))

# Progress indicator
progress_frame = tk.Frame(left_panel, bg=COLORS["bg_light"], pady=5)
progress_frame.pack(fill=tk.X)

status_label = tk.Label(progress_frame, 
                       text="Status: Ready",
                       font=normal_font,
                       bg=COLORS["bg_light"],
                       fg=COLORS["primary"])
status_label.pack(anchor=tk.W, pady=(0, 5))

progress = ttk.Progressbar(progress_frame, 
                          orient="horizontal", 
                          length=400, 
                          mode="determinate",
                          style="TProgressbar")
progress.pack(fill=tk.X, pady=(0, 10))

# Open folder button
open_folder_button = tk.Button(progress_frame, 
                              text="Open Save Location",
                              font=normal_font,
                              bg=COLORS["primary_dark"],
                              fg=COLORS["text_light"],
                              padx=10, pady=5,
                              command=open_save_location)
open_folder_button.pack(anchor=tk.E)

# Output log
output_frame = tk.LabelFrame(left_panel, 
                            text="Log", 
                            font=heading_font,
                            bg=COLORS["bg_light"],
                            fg=COLORS["text_dark"],
                            padx=10, pady=10)
output_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

output_text = scrolledtext.ScrolledText(output_frame, 
                                       width=80, height=12,
                                       font=("Consolas", 9),
                                       bg=COLORS["bg_dark"],
                                       fg=COLORS["text_light"])
output_text.pack(fill=tk.BOTH, expand=True)

# Configure text tags for colored output
output_text.tag_configure("success", foreground="#2ecc71")  # Green
output_text.tag_configure("error", foreground="#e74c3c")    # Red
output_text.tag_configure("warning", foreground="#f39c12")  # Orange
output_text.tag_configure("info", foreground="#3498db")     # Blue
output_text.tag_configure("heading", foreground="#9b59b6", font=("Consolas", 9, "bold"))  # Purple, bold

# Preview area
preview_frame = tk.LabelFrame(right_panel, 
                             text="Image Preview", 
                             font=heading_font,
                             bg=COLORS["bg_dark"],
                             fg=COLORS["text_light"],
                             padx=10, pady=10)
preview_frame.pack(fill=tk.BOTH, expand=True)

preview_label = tk.Label(preview_frame, 
                        text="Preview will appear here", 
                        bg=COLORS["bg_dark"],
                        fg=COLORS["text_light"],
                        width=30, height=15)
preview_label.pack(fill=tk.BOTH, expand=True)

# App info at the bottom
info_label = tk.Label(right_panel, 
                     text="Google Custom Search Image Downloader",
                     font=("Helvetica", 8),
                     bg=COLORS["bg_dark"],
                     fg=COLORS["text_light"])
info_label.pack(side=tk.BOTTOM, pady=10)

# Add some default text with usage instructions
log("🔎 Welcome to the Modern Image Search Tool!", "heading")
log("• Enter search terms (one per line) in the text box", "info")
log("• Set the number of images to download", "info")
log("• Choose a save directory", "info")
log("• Optionally, select search filters", "info")
log("• Click 'Search and Save Images' to begin", "info")
log("\nReady to search! Enter your queries and start.", "success")

root.mainloop()