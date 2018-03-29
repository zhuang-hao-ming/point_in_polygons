# -*- coding: utf-8 -*-

'''

判断点是否落在道路的30米缓冲区内的方法：

TAXI的gps log中存在异常, 可以很直观地认为距离道路超过30m的log就是异常log，为了识别出这些异常log有以下这些方法：

1. 遍历所有道路， 如果有道路距离log的距离<30m，则结束， 否则就是异常
2. 为所有道路生成30m缓冲区， 遍历所有缓冲区， 如果log和一个缓冲区相交，则结束， 否则就是异常
3. 在2的基础上为缓冲区建立Rtree索引，利用Rtree来做相交判断
4. 将2的所有缓冲区合并为一个大的polygon， 判断点是否在polygon内部



实验分析那种方法的效率最高？

3最好

'''

import time
from collections import OrderedDict

import fiona
import psycopg2
import numpy as np
from shapely.geometry import shape, mapping, Point
from shapely.ops import unary_union
from shapely.strtree import STRtree
import matplotlib.path as matPath

from config import config as db_config

def read_shp(shp_path):
    '''
    读入shp文件， 转为feature list

    Parameters:
    -----------
    shp_path : str
        shp文件名
    '''
    road_c = fiona.open(shp_path, 'r')
    road_list = list(road_c)
    road_c.close()
    return road_list

crs = {'init': 'epsg:32649'}
driver = 'ESRI Shapefile'
schema = {
    'properties': OrderedDict(
        [
            # ('f_id', 'int'),
            
        ]
    ),
    'geometry': 'Polygon'
}

shp_config = {
    'crs': crs,
    'driver': driver,
    'schema': schema
}

def make_buffer():
    '''
    生成buffer文件
    '''

    begin_tick = time.time()

    road_list = read_shp('./shp/connected_road.shp')
    # 新建shp
    buffers_c = fiona.open('./shp/output/road_buffer.shp', 'w', **shp_config)
    # 遍历道路， 生成缓冲区， 输出结果
    for idx, road in enumerate(road_list):
        print(idx)
        road = shape(road['geometry'])
        road_buffer = road.buffer(30)        
        rec = {
            'type': 'Feature',
            'id': '-1',
            'geometry': mapping(road_buffer),
            'properties': OrderedDict(
                [
                    # ('f_id', -1)
                ]
            )
        }
        buffers_c.write(rec)
        
    buffers_c.close()
    print('elpase {}'.format(time.time() - begin_tick))

def make_union():
    '''
    生成union buffer文件
    '''
    # 合并road_buffer
    # 读入road_buffer
    begin_tick = time.time()
    road_buffers = read_shp('./shp/output/road_buffer.shp')
    polygon_list = []
    for road_buffer in road_buffers:
        polygon_list.append(shape(road_buffer['geometry']))
    # merge    
    u = unary_union(polygon_list) # union 98.43s
    print('elpase {}'.format(time.time() - begin_tick))

    union_buffers_c = fiona.open('./shp/output/union_road_buffer.shp', 'w', **shp_config)    

    
    rec = {
        'type': 'Feature',
        'id': '-1',
        'geometry': mapping(u),
        'properties': OrderedDict(
            [
                # ('f_id', -1)
            ]
        )
    }
    union_buffers_c.write(rec)
    union_buffers_c.close()

def get_raw_log_data(day, hour=18):
    '''从数据库读取od数据

    Parameters:
    ----------
    day : int
        9月的日期
    hour : int
        小时{0-23}

    Returns:
    ---------
    rows : list
        [ (log_time, car_id, on_service, x, y, v), ...]
    '''
    sql = '''select log_time, car_id, on_service, ST_X(geom), ST_Y(geom), velocity from gps_log_9_{day} where EXTRACT(HOUR FROM log_time) = {hour} order by car_id, log_time limit 10000;'''.format(day=day, hour=hour)
    
    conn = None
    try:
        params = db_config()
        conn = psycopg2.connect(**params)
        cur = conn.cursor()        
        cur.execute(sql)        
        rows = cur.fetchall()
        cur.close()
        return rows
    except (Exception, psycopg2.DatabaseError) as error:
        print(error)
    finally:
        if conn is not None:
            conn.close()


def get_border_path(buffer):
    #
    # exterior + [0,0]
    # 插入1个moveto,n-1个lineto,1格closepoly
    # interior + [0,0]
    # 插入1个moveto,n-1个lineto,1格closepoly
    # concatecate在一起
    #
    betin_tick = time.time()
    ex_codes = [matPath.Path.MOVETO] + [matPath.Path.LINETO] * (len(buffer.exterior.coords)-1) + [matPath.Path.CLOSEPOLY]
    ex_vertex = list(buffer.exterior.coords)
    ex_vertex.append((0, 0))
    # print(len(ex_vertex))
    for interior in buffer.interiors:        
        in_codes = [matPath.Path.MOVETO] + [matPath.Path.LINETO] * (len(interior.coords)-1) + [matPath.Path.CLOSEPOLY]
        in_vertex = list(interior.coords)        
        in_vertex.append((0, 0))
        ex_codes.extend(in_codes)
        ex_vertex.extend(in_vertex)
    assert(len(ex_codes) == len(ex_vertex))
    # print('build path elapse {}'.format(time.time() - betin_tick))
    print(len(ex_vertex))
    print(len(buffer.interiors))
    # assert(len(buffer.interiors) == 0) # assert 没有内环， Path.contains_point对于有内环的矩形有效吗？ 有效
    border_path = matPath.Path(ex_vertex, ex_codes)

    # import matplotlib.pyplot as plt
    # from matplotlib.patches import PathPatch
    

    # axes = plt.gca()
    # patch = PathPatch(border_path)
    # axes.add_patch(patch)
    # axes.set_xlim(783540.186100,870767.634800)
    # axes.set_ylim(2487462.790800,2525302.672500)
    # plt.show()
    # plt.savefig('example.png')
    # plt.close('all')

    return border_path

def mpl_contain(point, border_path):
    '''
    使用matplotlib.path的contains_point方法
    来判断点是否在多边形内

    Parameters:
    ----------
    point : shapely point
    buffer : shapely buffer
    '''

    if border_path.contains_point([point.x, point.y]):
        return True
    else:
        return False




def buffers_contain_point(point, buffers):
    '''
    遍历检查多边形是否包含点
    '''
    for buffer in buffers:
        if buffer.contains(point):
            return True
    return False

def rtree_buffer_contain_point(point, buffer_rtree):
    '''
    使用rtree检查，多边形是否包含点
    '''
    candidates = buffer_rtree.query(point)
    for buffer in candidates:
        if buffer.contains(point):
            return True
    return False


def get_buffer_r_tree():
    '''
    读入buffer文件， 并将geometry转化为shapely geometry然后构建rtree
    '''
    buffers = read_shp('./shp/output/road_buffer.shp')
    shapely_buffers = []
    for buffer in buffers:
        shapely_buffers.append(shape(buffer['geometry']))
    buffer_rtree = STRtree(shapely_buffers)
    return buffer_rtree

def get_buffer(shp_path='./shp/output/road_buffer.shp'):    
    '''
    读入buffer文件， 并将geometry转化为shapely geometry
    '''
    buffers = read_shp(shp_path)
    shapely_buffers = []
    for buffer in buffers:
        shapely_buffers.append(shape(buffer['geometry']))
    return shapely_buffers


def get_road():
    '''
    读入road文件，并将geometry转化为shapely geometry
    '''
    road_list = read_shp('./shp/connected_road.shp')
    shapely_roads = []
    for road in road_list:
        shapely_roads.append(shape(road['geometry']))
    return shapely_roads

def road_dis_to_road_smaller_30(point, roads):
    '''
    遍历所有道路， 计算点到道路的距离， 如果存在距离<30m的情况， 则保留点

    Parameters:
    ----------
    point : shapely point
    roads : list of shapely geometry
    '''
    for road in roads:
        if point.distance(road) < 30:
            return True
    return False





def test1():
    '''
    缓冲区

    '''
    begin_tick = time.time()

    buffers = get_buffer()

    print('read buffer', time.time() - begin_tick) # 3.0651280879974365
    begin_tick = time.time()


    rows = get_raw_log_data(1)

    print('read data', time.time() - begin_tick) # 12.962503910064697
    begin_tick = time.time()

    mask_arr = []
    for idx, row in enumerate(rows):
        print(idx)
        x = row[3]
        y = row[4]
        if buffers_contain_point(Point(x, y), buffers):
            mask_arr.append(1)
        else:
            mask_arr.append(0)
    mask_arr = np.asarray(mask_arr)

    print(len(mask_arr))
    print(mask_arr.sum())

    print('filter data', time.time() - begin_tick) # 890.597149848938
    begin_tick = time.time()

def test2():
    '''
    缓冲区+rtree

    '''
    begin_tick = time.time()

    buffer_rtree = get_buffer_r_tree()

    print('read r tree', time.time() - begin_tick) # 3.0651280879974365
    begin_tick = time.time()

    rows = get_raw_log_data(1)

    print('read data', time.time() - begin_tick) # 12.962503910064697
    begin_tick = time.time()

    mask_arr = []
    for idx, row in enumerate(rows):
        print(idx)
        x = row[3]
        y = row[4]
        if rtree_buffer_contain_point(Point(x, y), buffer_rtree):
            mask_arr.append(1)
        else:
            mask_arr.append(0)
    mask_arr = np.asarray(mask_arr)
    print(len(mask_arr))
    print(mask_arr.sum()) # 8906

    print('rtree filter data', time.time() - begin_tick) # 22.9338641166687, 18.700677633285522(matplotlib.Path)
    begin_tick = time.time()

def test3():
    '''
    距离

    '''
    begin_tick = time.time()

    roads = get_road()

    print('read road', time.time() - begin_tick) # 1.4388256072998047
    begin_tick = time.time()

    rows = get_raw_log_data(1)

    print('read data', time.time() - begin_tick) # 12.962503910064697
    begin_tick = time.time()

    mask_arr = []
    for idx, row in enumerate(rows):
        print(idx)
        x = row[3]
        y = row[4]
        if road_dis_to_road_smaller_30(Point(x, y), roads):
            mask_arr.append(1)
        else:
            mask_arr.append(0)
    mask_arr = np.asarray(mask_arr)
    print(len(mask_arr))
    print(mask_arr.sum())

    print('road filter data', time.time() - begin_tick) # 1272.5551042556763
    begin_tick = time.time()


def test4():
    '''
    使用union buffer
    '''
    begin_tick = time.time()

    buffers = get_buffer('./shp/output/union_road_buffer.shp')

    print('read buffer', time.time() - begin_tick) # 0.17800140380859375
    begin_tick = time.time()

    assert(len(buffers) == 1)
    

    
    rows = get_raw_log_data(1)

    print('read data', time.time() - begin_tick) # 12.962503910064697
    begin_tick = time.time()

    mask_arr = []
    for idx, row in enumerate(rows):
        print(idx)
        x = row[3]
        y = row[4]
        if buffers_contain_point(Point(x,y), buffers)
            mask_arr.append(1)
        else:
            mask_arr.append(0)
    

    mask_arr = np.asarray(mask_arr)
    print(len(mask_arr))
    print(mask_arr.sum())

    print('union buffer filter data', time.time() - begin_tick) # 7681.886378288269
    begin_tick = time.time()

if __name__ == '__main__':
    # test1()
    # test2()
    # test3()
    test4()
    