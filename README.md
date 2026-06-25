# Video Processing for [Sony PWM-EX3](https://www.sony.de/electronics/support/professional-camcorders-handheld-camcorders/pmw-ex3)

Video processing scripts of raw recordings (motion jpeg) by a Sony PWM-EX3 camera: joining clips, cutting and color correction with **ffmpeg** on the cmdline.

## Workflow

Assuming Linux:

1. Download recordings via Mini-USB cable
  	- Mount the drives (2) of the camera to a path of your choice and use the script `get_files_from_cam.sh` (which is just a wrapper for a rsync call):

		  sh ./get_files_from_cam.sh /mnt/temp/BPAV/ /mnt/recode/recordings-raw/

2. The recordings are stored in 4 GB snippets. Use VLC player to find the start and end positions. They are needed in seconds to skip (*-ss* argument) at the beginning and the overall length (*-t* argument) of the resulting video.
3. With VLC playback of the raw material, also create a snapshot (frame) from the section to keep and open that in GIMP to adjust the color levels. In this dialog, select *edit these values as curves* to transfer them into the curves dialog. The color conversion can be further improved and the setting can be stored in a profile which is provided to the script in file `GimpCurvesConfig_recode260604.settings` in the example below.
4. Use the Python script `join_clips.py` to join, cut and adjust color:

		python3 join_clips.py recordings/BPAV/TAKR/BAM_2396/BAM_2396.SMI curves=GimpCurvesConfig_recode260604.settings -ss 238 -t 6912

	Further **ffmpeg** options for color conversion are implemented and forwarded:
	
	-	**lut3d**: A file path to the color correction profile by Sony for that camera. It showed to be oversaturated for the lighting conditions used (*Could be the wrong profile too, no idea*).

            lut3d=Look_profile_for_resolve_S-Gamut_Slog2/From_SLog2SGumut_To_LC-709TypeA_.cube
	- **huesaturation**, Adjust hue and saturation for color channels individually or all together:

		  huesaturation=hue=-10:saturation=-0.25:strength=100,
		  huesaturation=hue=25:saturation=-0.10:colors=r:strength=100,
	      huesaturation=hue=40:saturation=-0.3:colors=m:strength=100,
		  huesaturation=saturation=-0.30:colors=b:strength=100
