
### ------------------------------------------------------------------------------- ###
# This script collects details from each of the .yxmd files listed in
# local alteryx files and populates the  Alteryx_Settings tables 
### _______________________________________________________________________________ ###

### --- IMPORT MODULES --- ###
### ---------------------- ###
import xml.etree.ElementTree as ET
import pandas as pd
import datetime
import time
import os
import pyodbc
import getpass
import multiprocessing as mp
from os import listdir
from os.path import isfile, join,exists
import glob
import numpy as np
import requests
import traceback
from github import Github, GithubException
from apyori import apriori
import logging
from time import sleep

### ______________________ ###
### __________________________________________________________ ###
    
#Constants
ACCESS_TOKEN = ''
logging.basicConfig(filename = 'log.txt', format='[%(asctime)s] - (%(lineno)d) - {%(funcName)s:%(message)s}',  datefmt='%d-%b-%y %H:%M:%S',filemode='w',
level=logging.INFO)
logger = logging.getLogger('log.txt')


def generate_file_list():
    alteryxFilePath = os.getcwd()
    file_list = []
    for root, dirs, files in os.walk(alteryxFilePath):
        for file in files:
            if file.endswith('.yxmd'):
                file_list.append(root+'\\'+file)
    if len(file_list) == 0:
        logger.info('no files... yet')
    return file_list


def retrieve_files_from_git(f):
    gClient = Github(ACCESS_TOKEN)    
    keyword = 'alteryx'
    extension = 'yxmd'
    fileUrls = []

    query = keyword + ' extension:' + extension

    results = gClient.search_code(query, order = 'asc')    
    print(f'Found {results.totalCount} file(s)')

    for file in results:   
        if f < 70:          
            url = file.download_url
            fileName = url[url.rfind("/")+1:]
            if(exists(fileName) or "RunTests" in fileName):
                continue  #skips file if it exists in directory, moves on to next
            try:
                r = requests.get(url,headers={'User-Agent': 'Mozilla/5.0'})

                if r.status_code != 200:
                    logger.info(r.request.url) 
            except GithubException as e:
                logger.info(r.request.url + ' ' + str(e)) 
                if r.status_code == 403:
                    break
            logger.info('Download file from: ' + url)
            open(fileName,"wb").write(r.content)
            sleep(2) #as to not hit api secondary limit, however, this api is very unreliable
            f = f + 1
        else: 
            break
    return 0

    
### --- FUNCTION: FORMULATE Alteryx_Settings TABLE --- ###
### ---------------------------------------------------------------- ##

def ax_set_parser(f):
    # get settings for each alteryx workflow listed in Directory,
    # write to ax_set_results list for later concat into ax_set_df dataframe and 
    # write to Alteryx_Settings table.  
    # working lists
    wn_lst = []
    pe_lst = []
    smtp_lst = []
    au_lst = []
    co_lst = []
    cr_lst = []
    db_lst = []
    sm_lst = []
    tool_lst = []
#get windows properties
    try:       
        v_actime = time.ctime(os.path.getatime(f))
        v_mtime = time.ctime(os.path.getmtime(f))
        v_ctime = time.ctime(os.path.getctime(f))
        v_size = os.path.getsize(f)
        wn_lst.append({'FileName': f,'LastAccessDate': v_actime,'LastModifiedDate': v_mtime,'CreateDate': v_ctime,'FileByteSize': v_size})
#        print(wn_lst)
    except Exception as e:
        logger.info('Exception occured:'  + str(e))
#get XML data
    try:
        tree = ET.parse(f)
        root = tree.getroot()
        for i in root.iter('Description'):
            try:
                pe_lst.append({'PostExec':i.text,'FileName': f})
            except Exception as e:
                pass
        for i in root.iter('email_SMTPServer'):
            try:
                smtp_lst.append({'SMTPEmail':i.text,'FileName': f})
            except Exception as e:
                pass                     
        for i in root.iter('Author'):
            try:
                au_lst.append({'Author':i.text,'FileName': f})  
            except Exception as e:
                pass
        for i in root.iter('Company'):
            try:
                co_lst.append({'Company':i.text,'FileName': f})    
            except Exception as e:
                pass
        for i in root.iter('Copyright'):
            try:                     
                cr_lst.append({'Copyright':i.text,'FileName': f})    
            except Exception as e:
                pass  
        for i in root.iter('Properties'):
            for j in i:
                if j.tag == 'DisableBrowse':
                    try:                  
                        db_lst.append({'DisableBrowse': j.attrib.get('value'),'FileName': f})
                    except Exception as e:
                        pass
        for i in root.iter('Properties'):
            for j in i:
                if j.tag == 'ShowAllMacroMessages':
                    try:
                        sm_lst.append({'ShowAllMacroMessages': j.attrib.get('value'),'FileName': f})
                    except Exception as e:
                        pass
        for i in root.iter('GuiSettings'):
            try:
                res = []
                for l in range(len(i.attrib)):
                    res = list(i.attrib.values())[0] 
                tool_lst.append({'Tools':res,'FileName': f})    
            except Exception as e:
                logger.info('Exception occured:'  + str(e))
    except Exception as e:
        logger.info('Exception occured:'  + str(e))
    # #Create dataframe for the lists
    # #Windows 
    wn_df = pd.DataFrame()
    cols=['FileName','LastAccessDate','LastModifiedDate','CreateDate','FileByteSize']
    wn_df = pd.DataFrame(wn_lst, columns = cols)   
    wn_df['LastAccessDate']=pd.to_datetime(wn_df['LastAccessDate'])
    wn_df['LastModifiedDate']=pd.to_datetime(wn_df['LastModifiedDate'])
    wn_df['CreateDate']=pd.to_datetime(wn_df['CreateDate'])
    wn_df = wn_df.fillna(value='-')
    
    # #PostExec                 
    pe_df = pd.DataFrame()
    cols = ['FileName','PostExec']
    pe_df = pd.DataFrame(pe_lst, columns = cols)
    pe_df['PostExec'].fillna("False", inplace = True)
    for index, row in pe_df.iterrows():
        if 'After Run' in pe_df.loc[index,'PostExec']:
            pe_df.loc[index,'PostExec'].PostExec= 'T'
        else:
            pe_df.loc[index,'PostExec'] = 'False'  

    pe_df = pe_df[pe_df.PostExec.notnull()]

    pe_df = pe_df.fillna(value='-')
  
    try:
        pe_df = pe_df.groupby('FileName')['PostExec'].apply('|'.join).reset_index()
    except Exception as e:
        logger.info('Exception occured:'  + str(e))

    # #Author
    au_df = pd.DataFrame()
    cols = ['FileName','Author']
    au_df = pd.DataFrame(au_lst, columns = cols)  
    au_df = au_df.fillna(value='-') 


    # #Company
    co_df = pd.DataFrame()
    cols = ['FileName','Company']
    co_df = pd.DataFrame(co_lst, columns = cols) 
    co_df = co_df.fillna(value='-')  


    # #Copyright 
    cr_df = pd.DataFrame()
    cols = ['FileName','Copyright']
    cr_df = pd.DataFrame(cr_lst, columns = cols)
    cr_df = cr_df.fillna(value='-')  

    # #DisableBrowse    
    db_df = pd.DataFrame()
    cols = ['FileName','DisableBrowse']
    db_df = pd.DataFrame(db_lst, columns = cols)  
    db_df = db_df.fillna(value='-')  
    
    # #ShowAllMacroMessages    
    sm_df = pd.DataFrame()
    cols = ['FileName','ShowAllMacroMessages']
    sm_df = pd.DataFrame(sm_lst, columns = cols)
    sm_df = sm_df.fillna(value='-')  


    
    # #SMTPEmails
    smtp_df = pd.DataFrame()
    cols = ['FileName','SMTPEmail']
    smtp_df = pd.DataFrame(smtp_lst, columns = cols)
    smtp_df = smtp_df.fillna(value='-')  
    try:
        smtp_df = smtp_df.groupby('FileName', group_keys=True)['SMTPEmail'].apply('|'.join).reset_index()
    except Exception as e:
        logger.info('Exception occured:'  + str(e))

    if smtp_df.empty:
        emptyEmail = {'FileName' : [f],'SMTPEmail' : ['-']}
        smtp_df = pd.DataFrame(data=emptyEmail)

    # #tools
    tool_df = pd.DataFrame()
    try:    
        cols = ['FileName','Tools']
        tool_df = pd.DataFrame(tool_lst, columns = cols)      
        tool_df['Tools2']=tool_df['Tools'].str.extract(r'([^.]+$)')          
        del tool_df['Tools']
        tool_df['Tools'] = tool_df['Tools2']
        del tool_df['Tools2']
        tool_df = tool_df.dropna()
        tools_df = tool_df.groupby('FileName',group_keys=True)['Tools'].apply(' '.join).reset_index()
        del tool_df
        tools_df = tools_df.fillna(value='-') 
    except Exception as e:
        print('TOOLS_DF TRY info: ' + str(e))     
    # #Merge all dataframes, add run details
    try:

        ax_set_temp = pd.merge(pe_df, au_df)
        ax_set_temp = pd.merge(ax_set_temp, co_df)
        ax_set_temp = pd.merge(ax_set_temp, cr_df)
        ax_set_temp = pd.merge(ax_set_temp, db_df)
        ax_set_temp = pd.merge(ax_set_temp, sm_df)
        ax_set_temp = pd.merge(ax_set_temp, wn_df)
        ax_set_temp = pd.merge(ax_set_temp, smtp_df)
        ax_set_temp['RunDate']= datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ax_set_temp = pd.merge(ax_set_temp, tools_df)
        ax_set_temp = ax_set_temp.reindex(columns= ['FileName','PostExec','Author','Company','Copyright','DisableBrowse','ShowAllMacroMessages','LastAccessDate','LastModifiedDate','CreateDate','FileByteSize','SMTPEmail','RunDate','Tools'])
        for val in ax_set_temp.values.tolist(): # return each distinct entry
            return val
    except Exception as e:
            logger.info('Exception occured:'  + str(e))

### ________________________________________________________________ ###

### S
def association_rule_mining(f):
    try:
        toolslst = []
        for i in f:
            toolslst.append(i.split(' '))

        asc_cols = ['rule','support','confidence','lift']

        parsedResults = []
        association_rules = list(apriori(toolslst,min_support = 0.2, min_lift=2,min_confidence=0.2))
        for rule in association_rules:
            assoc = rule[0] 
            rules = [x for x in assoc] #breakdown to isolate the actual values        
            row = (",".join(rules),str(rule[1])[:7],str(rule[2][0][2])[:7],str(rule[2][0][3])[:7])
            parsedResults.append(row)
        asc_df = pd.DataFrame(parsedResults,columns = asc_cols)
        return asc_df
    except Exception as e:
        logger.info(traceback.format_exc())    

def database_operations(f):
    try:
        # truncate existing _Alteryx_IO, Alteryx_Settings tables
        set_trunc_stmt = "TRUNCATE TABLE dbo.Alteryx_Settings" #truncate the table, as this does a full directory scan every time the script is run
        rul_trunc_stmt = "TRUNCATE TABLE dbo.Association_Rules"
        cursor = conn.cursor()
        cursor.execute(set_trunc_stmt)     
        cursor.execute(rul_trunc_stmt)       #truncate tables to recreate tools and settings
        # write new results to  Alteryx_Settings
        set_cols = ['FileName','PostExec','Author','Company','Copyright','DisableBrowse','ShowAllMacroMessages','LastAccessDate','LastModifiedDate','CreateDate','FileByteSize','SMTPEmail','RunDate','Tools']
        ax_set_df = pd.DataFrame(f, columns = set_cols)

        ax_set_df = ax_set_df.dropna()

        as_rules =  association_rule_mining(ax_set_df['Tools'])
        #write rules to db
        set_ins_stmt = "INSERT INTO dbo.Alteryx_Settings(FileName,PostExec,Author,Company,Copyright,DisableBrowse,ShowAllMacroMessages,LastAccessDate,LastModifiedDate,CreateDate,FileByteSize,SMTPEmail,RunDate,Tools) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
        for r in ax_set_df.iterrows():           
            cursor.execute(set_ins_stmt,r[1].FileName,r[1].PostExec,r[1].Author,r[1].Company,r[1].Copyright,r[1].DisableBrowse,r[1].ShowAllMacroMessages,r[1].LastAccessDate,r[1].LastModifiedDate,r[1].CreateDate,r[1].FileByteSize,r[1].SMTPEmail,r[1].RunDate,r[1].Tools)
            
        conn.commit()



        MinFileSize = 15000
        while as_rules.empty and MinFileSize != 25000:
            ax_set_df = ax_set_df.drop(ax_set_df[ax_set_df.FileByteSize < MinFileSize].index, inplace = True)
            MinFileSize = MinFileSize + 5000
            as_rules =  association_rule_mining(ax_set_df['Tools'])
            print("No Association Rules Found, limiting search to file byte size of " + MinFileSize + " or above")  
            logger.INFO("No Association Rules Found, limiting search to file byte size of " + MinFileSize + " or above")  
        if not as_rules.empty:
            as_ins_stmt = "INSERT INTO dbo.Association_Rules(Association_Rule,Support,Confidence,Lift) VALUES (?,?,?,?)"
            for r in as_rules.iterrows():  
                cursor.execute(as_ins_stmt,r[1].rule,r[1].support,r[1].confidence,r[1].lift)
            conn.commit()

        else:
            print("No Association Rules found even after limiting search to file byte size of " + str(MinFileSize) + " or above")  
            logger.INFO("No Association Rules found even after limiting search to file byte size of " + str(MinFileSize) + " or above")  

    except Exception as e:
        logger.info('Exception occured:'  + str(e))
        conn.rollback()
        return 'Failure'
    finally:
        conn.close()
    return 'Success'


def test_results(): 
    test_conn = pyodbc.connect('DRIVER={ODBC Driver 17 for SQL Server};SERVER=MARO-AERO;DATABASE=CIS580;Trusted_Connection=yes')

    cursor = test_conn.cursor()
    file_list = generate_file_list()
    set_test_statement = "SELECT  fileName, tools FROM [CIS580].[dbo].[Alteryx_Settings]"
    asc_test_statement = "SELECT  top (1) * FROM [CIS580].[dbo].[Association_Rules]"
    table_records = []
    tools = []
    rule = []
    support = 0
    try:
        cursor.execute(set_test_statement)
        for row in cursor:
            table_records.append(row[0]) #get list without extra empty column
            tools.append(row[1])
        cursor.execute(asc_test_statement)
        rule = cursor.fetchone()
    except Exception as e:
        logger.info('Exception occured at testing select:'  + str(e))
        test_conn.close()
    finally:
        if test_conn:
            test_conn.close()
    if rule is not None:
        parsed_rule = rule[0].split(",")
        count = 0
        for i in tools:
            if all(x in i for x in parsed_rule):
                count = count + 1
            support = str(count/len(table_records))[:7] #support calculation and conversion
    else:  
        print("Support would not be tested successfully due to empty Dataset ")

    print(len(file_list))
    temp3 = []
    for element in file_list:
        if element not in table_records:
            temp3.append(element)
    print(temp3)
    table_records.sort()
    file_list.sort()        # sorting tables in alphabetical order to ensure a correct test
    assert table_records == file_list

    print('File test successful')
    assert support, rule[1] 
    print('Support test successful') 



### --- RUN SCRIPT --- ###
### ------------------ ###
if __name__=='__main__':

    #Select all Alteryx workflows from GAPG_NAS_Scanner table

    conn = pyodbc.connect('DRIVER={ODBC Driver 17 for SQL Server};SERVER=MARO-AERO;DATABASE=CIS580;Trusted_Connection=yes')

    file_list = generate_file_list()
    if len(file_list) < 60: #made to bypass github exception info, basically forces the code to continue 
        retrieve_files_from_git(len(file_list))      # if theres too little results, but stops it from generating too many
       
    # collection lists - necessary for multiprocessing
    ax_set_results = []

    # create and implement multiprocessing pool. Multiprocessing tool used to process multiple files at once
    pool = mp.Pool(processes = mp.cpu_count())
    ax_set_results.extend(pool.map(ax_set_parser, file_list))

    pool.close()
    
    # remove None type objects from lists
    ax_set_results = [x for x in ax_set_results if x]
    database_operations(ax_set_results)
    test_results()
