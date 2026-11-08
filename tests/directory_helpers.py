"""Tests may explicitly collect all pages; the browser API never returns all rows."""
def read_directory(client):
    directory={'version':2,'classes':[],'students':[],'class_counselors':[]}
    revision=None
    for view in ['classes','students']:
        page=1
        while True:
            response=client.get('/api/admin/directory',params={'view':view,'page':page})
            assert response.status_code==200,response.text
            result=response.json();revision=result['revision']
            for key in ['classes','students','class_counselors']:
                directory[key].extend({k:v for k,v in row.items() if k!='class_label'} for row in result['directory'][key])
            if page>=result['pages']:break
            page+=1
    return {'directory':directory,'revision':revision}
