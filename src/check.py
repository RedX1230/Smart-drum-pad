import cv2

for i in range(6):
    print("Trying index:", i)
    cap = cv2.VideoCapture(i, cv2.CAP_MSMF)

    if cap.isOpened():
        ret, frame = cap.read()
        if ret:
            print("Working index:", i)
            cv2.imshow("Cam", frame)
            cv2.waitKey(0)
            cap.release()
            break
    cap.release()