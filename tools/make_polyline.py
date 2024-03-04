import argparse
import csv
import json
import polyline

def extract_lat_lng(filename, offset, gnss_only):
    count = 0
    points = []
    points_gnss_1 = []
    points_gnss_2 = []
    with open(filename, 'r') as file:
        linenum = 0
        csv_reader = csv.reader(file)
        for line in csv_reader:
            linenum += 1
            count += 1
            if linenum == 1:
                continue
            try:
                # get the data as csv
                data = line
                lat = float(data[3])
                lng = float(data[4])
                if gnss_only == False and count % offset == 0:
                    points.append((lat, lng))

            except (KeyError, json.JSONDecodeError):
                print("Error parsing line or missing data:", line)
                continue

    return polyline.encode(points)

def main(): 
        argp = argparse.ArgumentParser()
        argp.add_argument('-j', '--json', type=str,
        help='JSON file to parse')
        argp.add_argument('-o', '--offset', type=int, default=1,
        help='Offset of frames to read')
        argp.add_argument('-g', '--gnss', type=bool, default = False,
        help='Only use gnss frames')
        args = argp.parse_args()
        pl_avg = extract_lat_lng(args.json, args.offset, args.gnss)
        print("Polyline Average: \n")
        print(pl_avg)
if __name__ == '__main__':
     main()