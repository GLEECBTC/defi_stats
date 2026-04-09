#!/bin/bash

# This should be run on a separate server so processing is decoupled from serving.

if [ $(hostname) = 'hound' ]; then
    username='hound'
elif [ $(hostname) = 'rates-komodo-earth' ]; then
    username='admin'
else
    username='atomic'
fi

project_folder="/home/${username}/defi_stats"
echo $project_folder
source "${project_folder}/api/.env"

# Move this to be accessible by the api container
/usr/bin/python3 "${project_folder}/api/db/backup_db.py" --src "${LOCAL_MM2_DB_PATH_SEED}" --dest "${project_folder}/api/db/local/MM2_8762.db"
/usr/bin/python3 "${project_folder}/api/db/backup_db.py" --src "${LOCAL_MM2_DB_PATH_SEED_6133}" --dest "${project_folder}/api/db/local/MM2_6133.db"

echo "Node type is: $NODE_TYPE"
if [ $NODE_TYPE = 'serve' ]; then
    echo "Sourcing pre-processed master databases"
    # Import cleaned, pre-processed source databases from the processing server (test.defi-stats.komodo.earth)
    #rsync -avzP admin@test.defi-stats.komodo.earth:/home/admin/defi_stats/api/db/master/MM2_7777.db                     "${project_folder}/api/db/source/MM2_7777.db"
    rsync -avzP admin@test.defi-stats.komodo.earth:/home/admin/defi_stats/api/db/master/MM2_8762.db                     "${project_folder}/api/db/source/MM2_8762.db"
    rsync -avzP admin@test.defi-stats.komodo.earth:/home/admin/defi_stats/api/db/master/MM2_6133.db                     "${project_folder}/api/db/source/MM2_6133.db"
    rsync -avzP admin@test.defi-stats.komodo.earth:/home/admin/defi_stats/api/db/master/MM2_all.db                      "${project_folder}/api/db/source/MM2_all.db"
    # Backup cleaned, pre-processed source databases into 'master' db folder
    #/usr/bin/python3 "${project_folder}/api/db/backup_db.py" --src "${project_folder}/api/db/source/MM2_7777.db" --dest "${project_folder}/api/db/master/MM2_7777.db"
    /usr/bin/python3 "${project_folder}/api/db/backup_db.py" --src "${project_folder}/api/db/source/MM2_8762.db" --dest "${project_folder}/api/db/master/MM2_8762.db"
    /usr/bin/python3 "${project_folder}/api/db/backup_db.py" --src "${project_folder}/api/db/source/MM2_6133.db" --dest "${project_folder}/api/db/master/MM2_6133.db"
    /usr/bin/python3 "${project_folder}/api/db/backup_db.py" --src "${project_folder}/api/db/source/MM2_all.db" --dest "${project_folder}/api/db/master/MM2_all.db"
    # If we need to process local dbs, they should be exported to test.defi-stats.komodo.earth
    # /usr/bin/python3 "${project_folder}/api/db/backup_db.py" --src "${HOST_LOCAL_MM2_DB_PATH_7777}"              --dest "${project_folder}/api/db/local/MM2_7777.db"

else
    # Import raw source databases from their respective servers for processing on test.defi-stats.komodo.earth
    echo "Sourcing seed node source databases for processing"
    rsync -avzP atomic@168.119.236.246:/DB/43ec929fe30ee72be42c9162c56dde910a05e50d/MM2.db     /home/${username}/defi_stats/api/db/source/seed7_MM2.db
    rsync -avzP atomic@168.119.236.246:/home/atomic/DB/seed2_MM2.db                            /home/${username}/defi_stats/api/db/source/seed2_MM2.db
    rsync -avzP atomic@168.119.236.246:/home/atomic/DB/seed3_MM2.db                            /home/${username}/defi_stats/api/db/source/seed3_MM2.db
    rsync -avzP atomic@168.119.236.246:/home/atomic/DB/viserion_MM2.db                         /home/${username}/defi_stats/api/db/source/viserion_MM2.db
    rsync -avzP atomic@168.119.236.246:/home/atomic/DB/rhaegal_MM2.db                          /home/${username}/defi_stats/api/db/source/rhaegal_MM2.db
    rsync -avzP atomic@168.119.236.246:/home/atomic/DB/drogon_MM2.db                           /home/${username}/defi_stats/api/db/source/drogon_MM2.db
fi
