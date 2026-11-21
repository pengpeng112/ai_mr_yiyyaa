docker exec med-audit bash -c "python /tmp/st2.py > /tmp/step_out.txt 2>&1" &
disown
