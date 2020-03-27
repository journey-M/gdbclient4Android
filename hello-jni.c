#include <stdio.h>
#include <pthread.h>
#include <sys/types.h>
#include <unistd.h>
#include <stdlib.h>


void * pth1(void*p)
{
	static uint m;
	while(1)
	{
		printf("this is in sub thread ! num:%d  \n",m);
		m++;
		sleep(3);
	}
}

int main (){

	pthread_t thread;
	pthread_create(&thread,NULL,pth1,NULL );
	printf("this is test in main \n");

	char* str = (char*)malloc(sizeof(char)*20) ;
	while(1){
		scanf("%s",str);
	}
}
