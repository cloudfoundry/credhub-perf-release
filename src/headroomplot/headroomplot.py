import sys
import os.path
import re
import warnings
from io import StringIO

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from patsy import dmatrices
import six

if __name__ == '__main__':
    matplotlib.style.use('ggplot')

    matplotlib.rcParams['figure.figsize'] = 9, 6
    matplotlib.rcParams['legend.loc'] = 'best'
    matplotlib.rcParams['figure.dpi'] = 120

    # We'll need these packages for plotting fit lines
    warnings.filterwarnings('ignore')
    performanceResultsFile = sys.argv[1]
    assert os.path.isfile(performanceResultsFile), 'Missing performance results file'

    compareDatasets = False

    if compareDatasets:
        assert os.path.isfile('old_perfResults.csv'), 'Missing old performance results file "old_perfResults.csv"'


class PerfData():
    __DATETIME_HEADER__ = "start-time"
    __PERF_HEADER__ = __DATETIME_HEADER__ + ",response-time"

    def __init__(self, filename):
        self._filename = filename

    def data(self):
        with open(self._filename) as f:
            _data = f.read()
        return _data

    def headers(self):
        return self.__PERF_HEADER__

    def datetime_headers(self):
        return self.__DATETIME_HEADER__


class PerformanceRunIterator():
    def __init__(self, data, header):
        self._data = data
        self._current_index = 0
        self._perf_header = header

    def __iter__(self):
        self._header_indexes = [m.start() for m in re.finditer(self._perf_header, self._data)]
        self._header_indexes.append(len(self._data))

        return self

    def next(self):
        if self._current_index + 1 >= len(self._header_indexes):
            raise StopIteration
        line = self.__getitemAt__(self._current_index)
        self._current_index = self._current_index + 1

        return line

    def __getitemAt__(self, position):
        start = self._header_indexes[position]
        end = self._header_indexes[position + 1]
        line = self._data[start:end]
        return six.text_type(line)


def readThroughputData(filename):
    perfData = PerfData(filename)

    df = pd.DataFrame()
    for run in PerformanceRunIterator(perfData.data(), perfData.headers()):
        run_dataframe = pd.read_csv(StringIO(run), parse_dates=[perfData.datetime_headers()])

        trimmedSection = trimEdges(run_dataframe)

        if len(trimmedSection) > 0:
            df = df.append(trimmedSection)

    # Reset the index because it is a Frankenstein of smaller indexes
    df = df.reset_index().drop('index', axis=1)
    return df


def trimEdges(data):
    indexes = data.set_index('start-time').resample('1S').aggregate(lambda x: 1).index
    testStartTime = indexes[0]
    testEndTime = indexes[-1]
    return data[(data['start-time'] >= testStartTime) & (data['start-time'] <= testEndTime)]

def processThroughputData(data):
    buckets = data.set_index('start-time')['response-time'].resample('1S')
    throughputDataSet = buckets.aggregate({"throughput": lambda x: 0 if x.count() == 0 else x.count()})

    throughputDataSet = throughputDataSet.reset_index()
    throughputDataSet = throughputDataSet.fillna(method='ffill')
    return buckets, throughputDataSet

if __name__ == '__main__':
    goData = readThroughputData(performanceResultsFile)

    throughputBuckets, throughputData = processThroughputData(goData)

    if compareDatasets:
        oldGoData = readThroughputData('old_perfResults.csv')
        oldThroughputBuckets, oldThroughputData = processThroughputData(oldGoData)

    goData['throughput'] = throughputBuckets.transform(len).reset_index()['response-time']
    goData.columns = ['start-time', 'latency', 'throughput']

    if compareDatasets:
        oldGoData['throughput'] = oldThroughputBuckets.transform(len).reset_index()['response-time']
        oldGoData.columns = ['start-time', 'latency', 'throughput']


def generateFitLine(data):
    y, x = dmatrices('latency ~ throughput', data=data, return_type='dataframe')
    fit = sm.GLM(y, x, family=sm.families.InverseGaussian(sm.families.links.inverse_squared)).fit()
    maxThroughput = data['throughput'].max()
    minThroughtput = data['throughput'].min()
    domain = np.arange(minThroughtput, maxThroughput)
    predictionInputs = np.ones((len(domain), 2))
    predictionInputs[:, 1] = domain
    fitLine = fit.predict(predictionInputs)
    return domain, fitLine, round(maxThroughput)

if __name__ == '__main__':
    domain, goFitLine, xLimit = generateFitLine(goData)

    if compareDatasets:
        oldDomain, oldGoFitLine, oldXLimit = generateFitLine(oldGoData)

    fig, ax = plt.subplots()

    # Change the value of `c` to change the color. http://matplotlib.org/api/colors_api.html
    ax = goData.plot(ax=ax, kind='scatter', x='throughput', y='latency', c='b', marker='.', alpha=0.2)
    ax.plot(domain, goFitLine, c='b', lw=2)  # Plot the fit line

    if compareDatasets:
        ax = oldGoData.plot(ax=ax, kind='scatter', x='throughput', y='latency', c='r', marker='.', alpha=0.2)
        ax.plot(oldDomain, oldGoFitLine, c='r', lw=2)  # Plot the fit line
        ax.legend(['after', 'before'])

    # To update x & y axis range change the parameters in function set_(x/y)lim(lower_limit, uppper_limit)

    ax.autoscale(True)
    ax.autoscale_view(True, True, True)
    plt.xlabel('Throughput (requests/sec)')
    plt.ylabel('Latency (sec)')
    plt.title('Headroom plot', y=1.05)
    plt.plot()

    filenameForPlot = performanceResultsFile[:-4] + "Plot.png"
    plt.savefig(filenameForPlot)
    print ("saving graph to " + filenameForPlot)
