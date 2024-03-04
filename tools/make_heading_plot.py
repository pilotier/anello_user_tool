import matplotlib.pyplot as plt
import argparse
import json
import csv

def main(): 
        
        argp = argparse.ArgumentParser()
        argp.add_argument('-j', '--json', type=str,
        help='JSON file to parse')
        argp.add_argument('-f', '--fps', type=int, default=1,
        help='FPS of data')
        args = argp.parse_args()
        framenum =0 
        headings = []
        framenums = []
        linenum = 0
        with open(args.json, 'r') as file:
            linenum = 0
            csv_reader = csv.reader(file)
            for line in csv_reader:
                linenum += 1
                if linenum == 1 or linenum % args.fps != 0:
                    continue
            
                try:
                    heading = float(line[11])
                    if heading < 0:
                        heading = 360 + heading
                    headings.append(heading)
                    framenums.append(linenum)




                except (KeyError, json.JSONDecodeError):
                    print("Error parsing line or missing data:", line)
                    continue

        fig, ax1 = plt.subplots(1, 1, layout='constrained')
        print(framenums)
        print(headings)
        ax1.plot( framenums, headings, label="Heading")
        ax1.grid(True)
        #ax2.plot(lats, lons, label="GPS")

        fig.legend()
        plt.show()
        
if __name__ == '__main__':
     main()