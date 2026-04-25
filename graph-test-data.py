#!/usr/bin/env python3

# Setup
#   bash
#   source .venv/bin/activate
#
#  then run python program

import pandas as pd
import numpy as np

def generate_weather_data(filename="data.csv"):
    # 1. Define our dimensions
    # We create a grid: 25 time steps (every hour) and 50 height levels
    times = np.linspace(0, 24, 25) 
    heights = np.linspace(0, 100, 50)
    
    data = []

    for t in times:
        for h in heights:
            # 2. Create a realistic temperature model
            # Base temp is 290K
            # - Subtract 0.6K for every meter of height (cooling as you go up)
            # - Add a sine wave for time to simulate day/night heating (peaks at 2 PM)
            base_temp = 280 
            lapse_rate = -0.5 * h
            diurnal_cycle = 15 * np.sin((t - 8) * np.pi / 12) 
            
            # Add a tiny bit of random noise for realism
            noise = np.random.uniform(-1, 1)
            
            temp = base_temp + lapse_rate + diurnal_cycle + noise
            
            # 3. Clip temperature to your requested 0-300 range
            temp = max(0, min(300, temp))
            
            data.append([round(temp, 2), round(h, 2), round(t, 2)])

    # 4. Save to CSV
    df = pd.DataFrame(data, columns=['temp', 'height', 'time'])
    df.to_csv(filename, index=False, header=False)
    print(f"Successfully generated {len(df)} rows of data in '{filename}'.")

if __name__ == "__main__":
    generate_weather_data()