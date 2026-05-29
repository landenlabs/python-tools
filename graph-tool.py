#!/usr/bin/env python3
# ----------------------------------------------------------------------
# Copyright (c) 2026 LanDen Labs - Dennis Lang
# https://landenlabs.com
# ----------------------------------------------------------------------

# Setup
#   bash
#   source .venv/bin/activate
#
#  then run python program

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.interpolate import griddata
import os

# 1. Setup Output Directory
output_dir = "plots_output"
if not os.path.exists(output_dir):
    os.makedirs(output_dir)

# 2. Load the data
try:
    # Adjust names to match your actual CSV header if it has one
    df = pd.read_csv('data.csv', names=['temp', 'height', 'time'])
except FileNotFoundError:
    # Dummy data generation for script testing
    times = np.linspace(0, 24, 100)
    heights = np.linspace(0, 100, 100)
    Time, Height = np.meshgrid(times, heights)
    Temp = 300 - (Height * 1.5) + np.sin(Time / 3.8) * 15
    df = pd.DataFrame({'temp': Temp.flatten(), 'height': Height.flatten(), 'time': Time.flatten()})

# 3. Create a smooth grid for interpolation
ti = np.linspace(df['time'].min(), df['time'].max(), 200)
hi = np.linspace(df['height'].min(), df['height'].max(), 200)
ti, hi = np.meshgrid(ti, hi)
zi = griddata((df['time'], df['height']), df['temp'], (ti, hi), method='cubic')

# 4. Generate 3D Surface Plot
fig1 = plt.figure(figsize=(10, 8))
ax1 = fig1.add_subplot(111, projection='3d')
surf = ax1.plot_surface(ti, hi, zi, cmap='magma', edgecolor='none', antialiased=True)
ax1.set_title('3D Temperature Profile (Height vs Time)')
ax1.set_xlabel('Time (0-24h)')
ax1.set_ylabel('Height (0-100m)')
ax1.set_zlabel('Temperature (0-300)')
fig1.colorbar(surf, shrink=0.5, aspect=10, label='Temp')

# Save 3D Plot
plot3d_path = os.path.join(output_dir, 'temperature_3d_surface.png')
plt.savefig(plot3d_path, dpi=300, bbox_inches='tight')
print(f"Saved 3D plot to: {plot3d_path}")

# 5. Generate 2D Contour Plot (Heatmap)
fig2, ax2 = plt.subplots(figsize=(10, 7))
contour = ax2.contourf(ti, hi, zi, levels=50, cmap='magma')
ax2.set_title('Temperature Heatmap (Time vs Height)')
ax2.set_xlabel('Time (0-24h)')
ax2.set_ylabel('Height (0-100m)')
fig2.colorbar(contour, label='Temperature')

# Save 2D Plot
plot2d_path = os.path.join(output_dir, 'temperature_2d_contour.png')
plt.savefig(plot2d_path, dpi=300, bbox_inches='tight')
print(f"Saved 2D plot to: {plot2d_path}")

# Show the plots on screen as well
plt.show()