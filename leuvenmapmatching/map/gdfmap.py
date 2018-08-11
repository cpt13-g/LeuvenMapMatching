# encoding: utf-8
"""
leuvenmapmatching.map.gdfmap
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Map based on the GeoPandas GeoDataFrame.

:author: Wannes Meert
:copyright: Copyright 2018 DTAI, KU Leuven and Sirris.
:license: Apache License, Version 2.0, see LICENSE for details.
"""
import logging
import time
from pathlib import Path
import pickle
from . import Map
import pandas as pd
import geopandas as gp
from shapely.geometry import Point
import pyproj
from functools import partial


logger = logging.getLogger("be.kuleuven.cs.dtai.mapmatching")


class GDFMap(Map):
    def __init__(self, use_latlon=True, crs_lonlat=None, crs_xy=None, graph=None):
        """
        In-memory representation of a map based on a GeoDataFrame.
        """
        super(GDFMap, self).__init__(use_latlon=use_latlon)
        self.graph = dict() if graph is None else graph
        self.nodes = None

        self.crs_lonlat = {'init': 'epsg:4326'} if crs_lonlat is None else crs_lonlat  # GPS
        self.crs_xy = {'init': 'epsg:3395'} if crs_xy is None else crs_xy  # Mercator projection
        proj_lonlat = pyproj.Proj(self.crs_lonlat, preserve_units=True)
        proj_xy = pyproj.Proj(self.crs_xy, preserve_units=True)

        self.lonlat2xy = partial(pyproj.transform, proj_lonlat, proj_xy)
        self.xy2lonlat = partial(pyproj.transform, proj_xy, proj_lonlat)

    def serialize(self):
        data = {
            "graph": self.graph,
            "use_latlon": self.use_latlon,
            "crs_lonlat": self.crs_lonlat,
            "crs_xy": self.crs_xy
        }
        return data

    @classmethod
    def deserialize(cls, data):
        return cls(use_latlon=data["use_latlon"],
                   crs_lonlat=data["crs_lonlat"], crs_xy=data["crs_xy"],
                   graph=data["graph"])

    def to_pickle(self, filename):
        filename = Path(filename)
        with filename.open("wb") as ofile:
            pickle.dump(self.serialize(), ofile)
        if self.nodes:
            with filename.with_suffix(".rtree").open("wb") as ofile:
                pickle.dump(self.nodes, ofile)

    @classmethod
    def from_pickle(cls, filename):
        filename = Path(filename)
        with filename.open("rb") as ifile:
            data = pickle.load(ifile)
        nmap = cls.deserialize(data)
        rtree = filename.with_suffix(".rtree")
        if rtree.exists():
            with rtree.open("rb") as ifile:
                nmap.nodes = pickle.load(ifile)
        return nmap

    def get_graph(self):
        return self.graph

    def bb(self):
        """Bounding box.

        :return: (lat_min, lon_min, lat_max, lon_max)
        """
        self.prepare_index()
        # glat, glon = zip(*[t[0] for t in self.graph.values()])
        # lat_min, lat_max = min(glat), max(glat)
        # lon_min, lon_max = min(glon), max(glon)
        lat_min, lon_min, lat_max, lon_max = self.nodes.total_bounds
        return lat_min, lon_min, lat_max, lon_max

    def labels(self):
        return self.graph.keys()

    def size(self):
        return len(self.graph)

    def coordinates(self):
        for t in self.graph.values():
            yield t[0]

    def node_coordinates(self, node_key):
        return self.graph[node_key][0]

    def add_node(self, node, loc):
        """
        :param node: label
        :param loc: (lat, lon) or (y, x)
        """
        if node in self.graph:
            if self.graph[node][0] is None:
                self.graph[node] = (loc, self.graph[node][1], self.graph[node][2])
        else:
            self.graph[node] = (loc, [], [])

    def add_edge(self, node_a, node_b):
        if node_a not in self.graph:
            raise ValueError(f"Add {node_a} first as node")
        if node_b not in self.graph:
            raise ValueError(f"Add {node_b} first as node")
        if node_b not in self.graph[node_a][1]:
            self.graph[node_a][1].append(node_b)
        if node_a not in self.graph[node_b][2]:
            self.graph[node_b][2].append(node_a)

    def all_edges(self):
        for key_a, (loc_a, nbrs, _) in self.graph.items():
            if loc_a is not None:
                for nbr in nbrs:
                    try:
                        loc_b, _, _ = self.graph[nbr]
                        if loc_b is not None:
                            yield (key_a, loc_a, nbr, loc_b)
                    except KeyError:
                        # print("Node not found: {}".format(nbr))
                        pass

    def all_nodes(self):
        for key_a, (loc_a, nbrs, _) in self.graph.items():
            if loc_a is not None:
                yield key_a, loc_a

    def purge(self):
        cnt_noloc = 0
        cnt_noedges = 0
        remove = []
        for node in self.graph.keys():
            if self.graph[node][0] is None:
                cnt_noloc += 1
                remove.append(node)
                # print("No location for node {}".format(node))
            elif len(self.graph[node][1]) == 0 and len(self.graph[node][1]) == 0:
                cnt_noedges += 1
                remove.append(node)
        for node in remove:
            del self.graph[node]
        print("Removed {} nodes without location".format(cnt_noloc))
        print("Removed {} nodes without edges".format(cnt_noedges))

    def prepare_index(self, force=False):
        if self.nodes is not None and not force:
            return

        if self.use_latlon:
            lats, lons, labels = [], [], []
            for label, data in self.graph.items():
                labels.append(label)
                lats.append(data[0][0])
                lons.append(data[0][1])
            df = pd.DataFrame(index=labels, data={'lat': lats, 'lon': lons})
            df['coordinates'] = list(zip(df.lon, df.lat))
            df['coordinates'] = df['coordinates'].apply(Point)
            self.nodes = gp.GeoDataFrame(df, geometry='coordinates', crs=self.crs_lonlat)

        else:
            ys, xs, labels = [], [], []
            for label, data in self.graph.items():
                labels.append(label)
                ys.append(data[0][0])
                xs.append(data[0][1])
            df = pd.DataFrame(index=labels, data={'y': ys, 'x': xs})
            df['coordinates'] = list(zip(df.x, df.y))
            df['coordinates'] = df['coordinates'].apply(Point)
            self.nodes = gp.GeoDataFrame(df, geometry='coordinates', crs=self.crs_lonlat)

    def to_xy(self):
        """Create a map that uses a projected XY representation on which Euclidean distances
        can be used.
        """
        if not self.use_latlon:
            return self

        self.prepare_index()
        nmap = GDFMap(use_latlon=False)
        print(self.nodes.head())
        nmap.nodes = self.nodes.to_crs(self.crs_xy)
        logger.debug("Projected all coordinates")
        print(nmap.nodes.head())
        # nmap.nodes['x'] = nmap.nodes.apply(lambda r: r['coordinates'].x, axis=1)
        # nmap.nodes['y'] = nmap.nodes.apply(lambda r: r['coordinates'].y, axis=1)
        for label, row in self.graph.items():
            point = nmap.nodes.loc[label]['coordinates']
            nmap.graph[label] = ((point.y, point.x), row[1], row[2])

        return nmap

    def latlon2xy(self, lat, lon):
        x, y = self.lonlat2xy(lon, lat)
        return y, x

    def xy2latlon(self, x, y):
        lon, lat = self.xy2lonlat(y, x)
        return lat, lon

    def preload_nodes(self, path, dist):
        pass

    def nodes_closeto(self, loc, max_dist=None, max_elmt=None):
        self.prepare_index()
        lat, lon = loc[:2]
        if False and max_dist is not None:
            nodes = self.nodes.cx[lon - max_dist: lon + max_dist,  # Longitude
                                  lat - max_dist: lat + max_dist]  # Latitude
        else:
            nodes = self.graph.keys()

        dists = nodes.distance(Point(lon, lat))
        dists.sort_values(inplace=True)
        if max_elmt is not None:
            dists = dists.iloc[:max_elmt]
        results = []
        for label, dist in dists.items():
            if dist > max_dist:
                break
            point = nodes.loc[label]['coordinates']
            results.append((dist, label, (point.y, point.x)))

        return results

    def nodes_nbrto(self, node):
        results = []
        if node not in self.graph:
            return results
        loc_node, nbrs, _ = self.graph[node]
        for nbr_label in nbrs + [node]:
            try:
                loc_nbr = self.graph[nbr_label][0]
                if loc_nbr is not None:
                    results.append((nbr_label, loc_nbr))
            except KeyError:
                pass
        return results

    def print_stats(self):
        print("Graph\n-----")
        print("Nodes: {}".format(len(self.graph)))

    def __str__(self):
        # s = ""
        # for label, (loc, nbrs, _) in self.graph.items():
        #     s += f"{label:<10} - ({loc[0]:10.4f}, {loc[1]:10.4f})\n"
        # return s
        return f"GDFMap(size={self.size()})"
