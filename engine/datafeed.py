from .common.mongo_utils import mongo
import pandas as pd
import re
import talib
import numpy as np
import requests
import json
from datetime import datetime

class FeatureParser(object):
    def __init__(self,df):
        self.df = df
        self.features_support={
            'return':self._parse_return,
            'ma':self._parse_ma,
        }

        self.funcs={
            'rank':self.rank
        }

    def rank(self,feature):{
        print('rank..............'+feature)
    }

    def _func_rank(self,basic_feature):
        se = self.df[basic_feature]
        pass

    def parse_operator(self,item):
        operators = ['+', '-', '*', '/']
        # 包含+,-,*,/
        splited = None
        for ope in operators:
            if ope in item:
                splited = item.split(ope)
        return splited

    #把features集合里，所有需要提取的因子都列出来
    def extra_features(self,items):
        features = []

        new_items = []
        for item in items:
            splited = self.parse_operator(item)
            if splited is None:
                new_items.append(item.strip())
            else:
                new_items.extend(splited)

        for item in new_items:
            ret =  re.search('([a-z]+_[\d+].*?$)',item)
            if ret:
               features.append(ret.group().strip())
        return list(set(features))


    #计算函数的:rank_avg_amount_5_20 => avg,rank,amount_5_20
    def extra_func(self,feature):
        funcs,args = self.parse_feature(feature)
        if funcs is None or args is None or len(funcs) <= 1:
            return None,None #没有函数

        feature = funcs[-1]
        for arg in args:
            feature = feature + '_' + str(arg)

        funcs = funcs[:len(funcs) -1]
        funcs.reverse()

        return funcs,feature


    def _parse_raw_item(self,feature,arg):
        return self.df[feature].shift(arg)

    def _parse_ma(self,arg):
        close = self.df['close']
        return talib.EMA(np.array(close), timeperiod=arg)

    def _parse_return(self,arg):
        close = self.df['close']
        return close / close.shift(arg) - 1

    def parse_feature(self,feature):
        #print(feature)
        for opt in ['+','-','*','/']:
            if opt in feature:
                return None,None
        items = feature.split('_')
        funcs = []
        args = []
        for item in items:
            if re.match('\d+$',item):
                args.append(int(item))
            else:
                funcs.append(item)
        return funcs,args


    def parse_all_features(self,features):
        #先把所有要计算的特征算好，存在df里
        basic_features = self.extra_features(features)
        for feature in basic_features:
            items = feature.split('_')
            feature_name = items[0]
            feature_args = int(items[1])
            if feature_name in self.features_support.keys():
                self.df[feature] = self.features_support[feature_name](feature_args)
            else:
                self.df[feature] = self._parse_raw_item(feature_name,feature_args)

        #avg_amount_5这样的函数运算
        for feature in features:
            funcs,feature_name = self.extra_func(feature)
            if funcs is None:
                continue
            else:
                for func in funcs:
                    if func in self.funcs.keys():
                        self.funcs[func](feature_name)
            #for func in funcs:

        #计算+-*/
        for feature in features:
            splited = self.parse_operator(feature)
            if splited:
                new_name = ''
                for item in splited:
                    new_name += item
                    new_name += '_'


                test = self.df.eval(new_name+'='+feature)
                #print(test)
        return self.df

class DataFeed(object):
    def __init__(self):
        self.idx = 0

    def get_benchmark_index(self):
        return self.all_dfs[self.benchmark].index

    def get_benchmark_return(self):
        return self.all_dfs[self.benchmark]['return_0']

    #往前走一步，如果超过范围返回done
    def step(self):
        bars = {}
        for instrument in self.all_dfs.keys():
            bars[instrument] = self.all_dfs[instrument].iloc[self.idx]
        self.idx += 1
        done = self.idx >= len(self.all_dfs[self.benchmark])
        return bars, done

    def calc_features(self,df,features):
        parser = FeatureParser(df=df)
        return parser.parse_all_features(features=features)

    def auto_label(self,df,hold_days=5):
        return_hold = 'return_hold'
        df[return_hold] = (df['close'].shift(hold_days) / df['close'] - 1)

        label_name = return_hold
        df = df.dropna(axis=0, how='any', thresh=None)
        df['label'] = df[return_hold]*100 + 10 #[0,20]
        df['label'] = df['label'].apply(lambda x:int(x))
        return df

    #加载所有instruments的数据
    def load_datas(self,instruments,features, start_date, end_date, benchmark='000300_index'):
        self.all_dfs = {}
        self.all_dfs[benchmark] = self._load_data(benchmark,start_date,end_date)

        for instrument in instruments:
            df = self._load_data(instrument,start_date,end_date)
            df = self.calc_features(df,features)
            df = self.auto_label(df)
            self.all_dfs[instrument] = df
        return self.all_dfs

    def _load_data(self,instrument,start_date,end_date):
        #items = mongo.query_docs('astock_daily_quotes', {'code': instrument,
        #                                                 'date': {'$gt': start_date, '$lt': end_date}},
        #                         )

        url = 'http://ailabx.com/kensho/quotes?code={}&start={}&end={}'.format(
            instrument,
            start_date.strftime('%Y%m%d'),
            end_date.strftime('%Y%m%d')
        )

        json_data = requests.get(url).json()
        data = json.loads(json_data['data'])
        df = pd.DataFrame(data)

        df.index = df['date']
        df.sort_index(inplace=True)
        del df['date']

        #基本面数据
        fundamentals = self.fundamentals(instrument,start_date,end_date)
        fundamentals = fundamentals.reindex(df.index,method='bfill',fill_value=0.0)

        df = df.join(fundamentals)
        df['pe'] = df['close'] / df['EPS']
        df['pb'] = df['close'] / df['NAPS']

        return df


    def instruments(self,start_date,end_date):
        url = 'http://www.ailabx.com/kensho/instruments?&start={}&end={}'.format(
            start_date.strftime('%Y%m%d'),
            end_date.strftime('%Y%m%d')
        )

        json_data = requests.get(url).json()
        data = json.loads(json_data['data'])
        df = pd.DataFrame(data)
        return list(df['code'])

    def fundamentals(self,code,start_date,end_date):
        url = 'http://www.ailabx.com/kensho/maindata?code={}&start={}&end={}'.format(
            code,
            start_date.strftime('%Y%m%d'),
            end_date.strftime('%Y%m%d')
        )

        json_data = requests.get(url).json()
        data = json.loads(json_data['data'])
        df = pd.DataFrame(data)
        df.index = df['EndDate']
        del df['code']
        return df


D = DataFeed()