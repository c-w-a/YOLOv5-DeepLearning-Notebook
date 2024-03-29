
# -- written by cwa -- 22/11/2023

import concurrent.futures
import pandas as pd
from pytube import YouTube
import random
import shutil
import subprocess
import os
import time
import fnmatch
import glob

# this script is for creating a training-ready (images and labels) subset of the YouTube-BB dataset 

# set these variables :
dataset = 'extra'           # name the new dataset                                                  
classes = ['dog']               # specify which classes to use
max_videos_to_download = 50    # specify how many youtube videos to download                        
class_remapping = {19: 0}        # specify class remapping 
train_ratio = 0.68              # specify train ratio
val_ratio = 0.16                # specify val ratio
test_ratio = 0.16               # specify test ratio *SET TO ZERO IF TEST DATA NOT DESIRED*
shuffle = True                  # shuffle filtered videos before downloading
                            
#thoughts:                            
# ..i should write a function to automate class remapping.. 
# ..i should also automate the creation of the .yaml file..
# ..more error handling..
# ..add option to manually inspect one bounding box overlay after data processing..
# also a check for duplicate dataset name.. overwrite or nah

# functions:
# function used to download video (called my multiple threads)
def download_video(video_id):
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        yt = YouTube(url)
        stream = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()
        stream.download(video_download_directory)
        name_to_id[yt.title] = video_id
        return [f"       success! ID {video_id} TITLE {yt.title}", True]
    except Exception as e:
        return [f"         FAILED ID {video_id} ERROR {str(e)}", False]

# function used to rename the rextracted frames to match yolov5 expected format
def rename_frames(timestamps, video_id):
    
    pattern = f"{video_id}_*.jpg"
    extracted_frames = sorted([f for f in os.listdir(image_directory) if fnmatch.fnmatch(f, pattern)])
    
    if len(extracted_frames) != len(timestamps):
        print("\n       uh-oh: the number of extracted frames and timestamps do not match")
        return

    for frame_file, timestamp in zip(extracted_frames, timestamps):
        original = os.path.join(image_directory, frame_file)
        new_filename = f"{video_id}_{timestamp}.jpg"
        new_path = os.path.join(image_directory, new_filename)
        os.rename(original, new_path)

# function used to extract all frames in dataset from one video
def extract_frames(video_path, timestamps, video_id):
    
    timestamps_sec = [timestamp / 1000 for timestamp in timestamps]
    select_filter = '+'.join([f'eq(n,{int(ts * 30)})' for ts in timestamps_sec])
    
    output_pattern = os.path.join(image_directory, f"{video_id}_%04d.jpg")

    ffmpeg_command = [
        'ffmpeg',
        '-i', video_path,
        '-vf', f'select=\'{select_filter}\',setpts=N/FRAME_RATE/TB',
        '-vsync', 'vfr',
        '-q:v', '2',
        output_pattern
    ]

    try:
        subprocess.run(ffmpeg_command, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Failed frame extraction: {e}")

# function for use of multithreaded when processing videos
def process_video(video_name):
    
    if pd.isna(video_name):
        return

    video_id = name_to_id[video_name]
    video_path = os.path.join(video_download_directory, f"{video_name}.mp4")

    if not os.path.exists(video_path):
        return

    label_rows = filtered_df[filtered_df.iloc[:,0] == video_id]
    timestamps = label_rows.iloc[:,1].tolist()

    extract_frames(video_path, timestamps, video_id)
    rename_frames(timestamps, video_id)

# function used for creating annotations in yolo format
def create_annontation(row):
    xmin, xmax, ymin, ymax = row[6], row[7], row[8], row[9]
    x_center = ((xmin + xmax) / 2) 
    y_center = ((ymin + ymax) / 2)
    width = (xmax - xmin)
    height = (ymax - ymin)
    if xmin == -1:
        return None
    return f"{row[2]} {x_center} {y_center} {width} {height}"

# function used to determine if object is in frame
def object_present(df, video_id, timestamp):
    row = df[(df[0] == video_id) & (df[1] == timestamp)]
    if not row.empty:
        
        return row.iloc[0][5] == 'present'  
    else:
        return False

# function used for changing the class IDs
def remap_classes(directory, dictionary):
    for label in os.listdir(directory):
        if label.endswith('.txt'):
            with open(os.path.join(directory, label), 'r') as file:
                lines = file.readlines()
            with open(os.path.join(directory, label), 'w') as file:
                for line in lines:
                    components = line.strip().split()
                    class_id = int(components[0])
                    if class_id in dictionary:
                        components[0] = str(dictionary[class_id])
                        file.write(' '.join(components) + '\n')

# function used to get label path from image path
def image_to_label_path(image_path):
    label_path = image_path.replace('/images/', '/labels/')

    label_path = label_path.rsplit('.', 1)[0] + '.txt'

    return label_path

# function used to move data
def move_data(image_paths, image_dir, label_dir):
    for image_path in image_paths:
        
        label_path = image_to_label_path(image_path)
        
        shutil.move(image_path, image_dir)
        
        if os.path.exists(label_path):
            shutil.move(label_path, label_dir)

print('\n\n-> CREATING DATASET : STARTING..')

print('\n       DATASET NAME : ' + dataset)
print('\n       CLASSES : ' + str(classes))
print('\n       MAX # OF VIDEOS TO DOWNLOAD : ' + str(max_videos_to_download))
print('\n       TRAIN RATIO : ' + str(train_ratio))
print('\n       VAL RATIO : ' + str(val_ratio))
print('\n       TEST RATIO : ' + str(test_ratio))

# CSV TO MP4
print('\n\n -- CSV TO MP4 : STARTING..')

print('\n -- loading YTBB .csv datasets..')
train_csv = '../../data/raw/yt_bb_detection_train.csv'
validate_csv = '../../data/raw/yt_bb_detection_validation.csv'
train_df = pd.read_csv(train_csv, header=None)
validate_df = pd.read_csv(validate_csv, header=None)
all_df = pd.concat([train_df, validate_df])

print('\n -- filtering for selected classes..')
filtered_df = all_df[all_df.iloc[:,3].isin(classes)]

print('\n -- finding all unique video IDs..')
unique_video_ids = filtered_df.iloc[:,0].unique()

if shuffle:
    random.shuffle(unique_video_ids)

os.makedirs('../../data/temp/')
video_download_directory = '../../data/temp' 

print('\n -- downloading videos (come back in some hours)..\n')
download_count = 0
name_to_id = {}

start_time = time.time()

with concurrent.futures.ThreadPoolExecutor(max_workers=7) as executor:
    
    results = executor.map(download_video, unique_video_ids[:max_videos_to_download])

    for result in results:
        print(result[0])
        if result[1] == True:
            download_count = download_count + 1

print('\n -- downloaded ' + str(download_count) + ' videos :)')

print('\n -- creating dictionaries..')
id_to_name = {value: key for key, value in name_to_id.items()}

print("\n -- CSV TO MP4 : ALL DONE ! :)")

# MP4 TO IMAGES & LABELS
print('\n\n -- MP4 TO IMAGES & LABELS : STARTING..')

print('\n -- matching downloaded mp4s with youtube IDs..')
filtered_df[10] = filtered_df.iloc[:,0].map(id_to_name)

print('\n -- converting videos into images and labels..')
data_directory = '../../data/processed/' + dataset + '/data/'
image_directory = '../../data/processed/' + dataset + '/data/images/'
label_directory = '../../data/processed/' + dataset + '/data/labels/'
os.makedirs(data_directory, exist_ok=True)
os.makedirs(image_directory, exist_ok=True)
os.makedirs(label_directory, exist_ok=True)

with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    video_names = filtered_df.iloc[:,10].unique()
    executor.map(process_video, video_names)

for video_name in filtered_df.iloc[:,10].unique():
     
    if pd.isna(video_name):
        continue
    
    video_id = name_to_id[video_name]

    label_rows = filtered_df[filtered_df.iloc[:,0] == video_id]

    for _, row in label_rows.iterrows():
        timestamp = row[1]
        label = create_annontation(row)

        if label is None:
            continue

        image_filename = f"{video_id}_{timestamp}"
        label_filename = image_filename + '.txt'
        label_output_path = os.path.join(label_directory, label_filename)

        with open(label_output_path, 'w') as file:
            file.write(label)

print('\n -- deleting images with object present, but without corresponding label..')
for image in os.listdir(image_directory):
    if image.endswith('.jpg'):
        video_id, timestamp = os.path.splitext(image)[0].rsplit('_', 1)
        label_path = image_to_label_path(os.path.join(image_directory, image))

        if object_present(filtered_df, video_id, timestamp):
            if not os.path.exists(label_path):
                os.remove(os.path.join(image_directory, image))
        else:
            pass

print('\n -- MP4 TO IMAGES & LABELS : ALL DONE ! :)')

# CLASS REINDEX
print('\n\n -- REINDEX CLASS IDs IN LABELS : STARTING..')

print('\n -- reindexing classes..')
remap_classes(label_directory, class_remapping)

print('\n -- REINDEX CLASS IDs IN LABELS : DONE ! :)')

# SPLIT DATA
print('\n\n -- SPLIT DATA : STARTING..')

print('\n -- listing all image paths..')
image_paths = [os.path.join(image_directory, image) for image in os.listdir(image_directory) if image.endswith('.jpg')]

print('\n -- finding split indices..')
image_count = len(image_paths)
train_end = int(image_count * train_ratio)
if test_ratio != 0:
    validation_end = train_end + int(image_count * val_ratio)

print('\n -- splitting lists..')
train_image_paths = image_paths[:train_end]
if test_ratio != 0:
    val_image_paths = image_paths[train_end:validation_end]
    test_image_paths = image_paths[validation_end:]
else:
    val_image_paths = image_paths[train_end:]
    test_image_paths = None

print('\n -- creating directories..')
os.makedirs(image_directory + 'train/', exist_ok=True)
os.makedirs(image_directory + 'val/', exist_ok=True)
os.makedirs(label_directory + 'train/', exist_ok=True)
os.makedirs(label_directory + 'val/', exist_ok=True)
if test_ratio != 0:
    os.makedirs(image_directory + 'test/', exist_ok=True)
    os.makedirs(label_directory + 'test/', exist_ok=True)

print('\n -- moving data..')
move_data(train_image_paths, image_directory + 'train/', label_directory + 'train/')
move_data(val_image_paths, image_directory + 'val/', label_directory + 'val/')
if test_ratio != 0:
    move_data(test_image_paths, image_directory + 'test/', label_directory + 'test/')

print('\n -- SPLIT DATA : ALL DONE ! :)')

# CLEANING UP
print('\n\n -- CLEANING UP : STARTING..')

print('\n -- deleting mp4s and temp folder..')
shutil.rmtree(video_download_directory)

print('\n -- deleting any unused labels from failed video downloads..')
txt_files = glob.glob(os.path.join('../../data/processed/' + dataset + '/data/labels/', '*.txt'))

for file_path in txt_files:
    try:
        os.remove(file_path)
    except OSError as e:
        print(f"       error: {file_path} : {e.strerror}")

print('\n -- CLEANING UP : DONE ! :)')

print('\n\n<- CREATING DATASET : DONE ! :)\n\n')