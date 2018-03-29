# -*- encoding: utf-8 -*-
'''
测试 matplotlib.path.Path.contains_point支不支持带洞的多边形

不支持!
'''

from matplotlib.path import Path
from matplotlib.patches import PathPatch
import matplotlib.pyplot as plt

if __name__ == '__main__':

    axes = plt.gca()
    points = [(0, 0), (20, 0), (20, 20), (0, 20), (0, 0), (5, 5), (5, 10),
              (10, 10), (10, 5), (0, 0)]
    codes = [
        Path.MOVETO, Path.LINETO, Path.LINETO, Path.LINETO, Path.CLOSEPOLY,
        Path.MOVETO, Path.LINETO, Path.LINETO, Path.LINETO, Path.CLOSEPOLY
    ]
    path = Path(points, codes)
    patch = PathPatch(path)
    axes.set_xlim(0, 20)
    axes.set_ylim(0, 20)
    axes.add_patch(patch)
    axes.plot([8,8],[8,15],'ro')
    

    print(path.contains_point([8,8])) # True
    print(path.contains_point([8,15])) # True
    print(path.contains_point([25,25])) # False
    plt.show()